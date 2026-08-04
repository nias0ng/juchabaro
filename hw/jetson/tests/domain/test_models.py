"""Jetson 목표 도메인 모델의 축 분리와 핵심 불변식."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.communication.models import (
    BACKEND_INTEGER_MAX,
    BACKEND_LONG_MAX,
    MoveRequestId,
    MoveVerificationAttempt,
    MoveVerificationIncidentResult,
    MoveVerificationResult,
    MoveVerificationState,
)
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.parking.models import (
    AssignmentState,
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentKeyScope,
    IncidentSignal,
    IncidentSignalValue,
    IncidentState,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    PhysicalExitEvidence,
    PhysicalTerminationOrigin,
    SessionAdministrativeState,
    SessionContext,
)
from src.tracking.models import (
    ParkingSessionId,
    MotionSignal,
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleId,
    TrackSegmentId,
    TrackingBatch,
    VehicleId,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)


def test_observation_state_is_not_a_domain_terminal_state() -> None:
    unknown = ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.TRACK_LOST,
        last_reliable_observed_at=NOW,
    )

    assert unknown.state is ObservationState.UNKNOWN
    assert not hasattr(ObservationState, "RESOLVED")

    with pytest.raises(ValueError, match="last_reliable"):
        ObservationStatus(state=ObservationState.OBSERVED)


def test_tracking_loss_and_confirmed_absence_are_separate_signals() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    batch = TrackingBatch(
        camera_id="camera-1",
        frame_id=1,
        observed_at=NOW,
        vehicles=(),
        ended_track_segment_ids=(TrackSegmentId(9),),
        unobserved_physical_vehicle_ids=(vehicle_id,),
        absence_progress=(
            PhysicalVehicleAbsenceProgress(vehicle_id, trusted_seconds=0.0),
        ),
        observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.CAMERA_UNAVAILABLE,
        ),
        full_area_observed=False,
        all_detections_tracked=True,
    )

    assert batch.ended_track_segment_ids == (TrackSegmentId(9),)
    assert batch.unobserved_physical_vehicle_ids == (vehicle_id,)
    assert batch.not_present_confirmed_vehicle_ids == ()
    assert batch.observation.state is ObservationState.UNKNOWN

    replayed_confirmation = TrackingBatch(
        camera_id="camera-1",
        frame_id=2,
        observed_at=NOW,
        vehicles=(),
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(vehicle_id,),
        absence_progress=(
            PhysicalVehicleAbsenceProgress(
                vehicle_id,
                trusted_seconds=5.0,
                confirmed_at=NOW,
            ),
        ),
        observation=ObservationStatus(
            state=ObservationState.DEGRADED,
            reason=ObservationReason.PARTIAL_FRAME,
            last_reliable_observed_at=NOW,
        ),
        full_area_observed=False,
        all_detections_tracked=True,
        not_present_confirmed_vehicle_ids=(vehicle_id,),
    )

    # 확정은 과거 정상 전체 관측에서만 만들어지지만, commit ack 전까지
    # 이어지는 degraded sample에도 같은 사실을 반복할 수 있다.
    assert replayed_confirmation.not_present_confirmed_vehicle_ids == (vehicle_id,)

    with pytest.raises(ValueError, match="unobserved PhysicalVehicle"):
        TrackingBatch(
            camera_id="camera-1",
            frame_id=3,
            observed_at=NOW,
            vehicles=(),
            ended_track_segment_ids=(),
            unobserved_physical_vehicle_ids=(),
            absence_progress=(),
            observation=OBSERVED,
            full_area_observed=True,
            all_detections_tracked=True,
            not_present_confirmed_vehicle_ids=(vehicle_id,),
        )


def test_zone_definition_uses_single_ev_charging_type() -> None:
    zone = ZoneDefinition(
        zone_id=ZoneId(1),
        zone_type=ZoneType.EV_CHARGING,
        polygon=((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(3),
        calibration_reference="camera-1:v2",
        allowed_duration_seconds=3600,
        charger_class="SLOW",
    )

    assert zone.zone_type is ZoneType.EV_CHARGING
    assert not hasattr(ZoneType, "EV_FAST")

    with pytest.raises(ValueError, match="only for EV_CHARGING"):
        ZoneDefinition(
            zone_id=ZoneId(2),
            zone_type=ZoneType.GENERAL,
            polygon=((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)),
            zone_definition_version=ZoneDefinitionVersion(3),
            calibration_reference="camera-1:v2",
            allowed_duration_seconds=3600,
        )


def test_incident_key_has_one_explicit_continuity_scope() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    key = IncidentKey.for_physical_vehicle(vehicle_id, "BAD_PARKING")
    signal = IncidentSignal(
        key=key,
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=NOW,
    )

    assert key.scope_type is IncidentKeyScope.PHYSICAL_VEHICLE
    assert key.scope_id == vehicle_id
    assert signal.value is IncidentSignalValue.UNKNOWN
    assert not hasattr(key, "parking_episode_id")


def test_candidate_is_durable_but_has_no_publication_revision() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    incident = Incident(
        incident_id=IncidentId(uuid4()),
        key=IncidentKey.for_physical_vehicle(vehicle_id, "AISLE_BLOCK"),
        physical_vehicle_id=vehicle_id,
        state=IncidentState.CANDIDATE,
        observation=OBSERVED,
        confirm_trusted_seconds=0,
        clear_trusted_seconds=0,
        confirm_duration_seconds=2,
        clear_duration_seconds=2,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        publication_revision=0,
        first_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    assert incident.state is IncidentState.CANDIDATE
    assert incident.publication_revision == 0


def test_local_only_open_incident_is_separate_from_publication_eligibility() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    common = dict(
        incident_id=IncidentId(uuid4()),
        key=IncidentKey.for_physical_vehicle(vehicle_id, "BAD_PARKING"),
        physical_vehicle_id=vehicle_id,
        state=IncidentState.OPEN,
        observation=OBSERVED,
        confirm_trusted_seconds=1,
        clear_trusted_seconds=0,
        confirm_duration_seconds=0,
        clear_duration_seconds=0,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        first_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        confirmed_at=NOW,
    )

    local_only = Incident(**common, publication_revision=0)
    assert local_only.state is IncidentState.OPEN
    assert local_only.publication_revision == 0

    with pytest.raises(ValueError, match="requires entryAttempt or session"):
        Incident(**common, publication_revision=1)


def test_candidate_state_timestamps_are_not_optional() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    with pytest.raises(ValueError, match="entered_candidate_at"):
        ZoneVisit(
            visit_id=ZoneVisitId(uuid4()),
            physical_vehicle_id=vehicle_id,
            zone_id=ZoneId(1),
            zone_definition_version=ZoneDefinitionVersion(1),
            state=ZoneVisitState.ENTERING,
            observation=OBSERVED,
            entry_trusted_seconds=0,
            exit_trusted_seconds=0,
            entry_confirmation_seconds=0,
            exit_confirmation_seconds=0,
            trusted_sample_max_gap_seconds=1,
            record_version=1,
            created_at=NOW,
            updated_at=NOW,
        )

    assignment = ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        representative_footprint=((0.0, 0.0), (1.0, 0.0), (0.5, 1.0)),
        confidence=0.9,
        last_stable_at=NOW,
        zone_id=ZoneId(1),
    )
    with pytest.raises(ValueError, match="movement_candidate_at"):
        ParkingEpisode(
            episode_id=ParkingEpisodeId(uuid4()),
            physical_vehicle_id=vehicle_id,
            state=ParkingState.MOVE_PENDING,
            observation=OBSERVED,
            stationary_trusted_seconds=600,
            movement_trusted_seconds=0,
            parking_confirmation_seconds=600,
            movement_confirmation_seconds=0,
            trusted_sample_max_gap_seconds=1,
            last_signal=MotionSignal.MOVING,
            record_version=1,
            publication_revision=1,
            created_at=NOW,
            updated_at=NOW,
            assignment=assignment,
            parked_at=NOW,
        )


def test_canceled_relation_is_not_marked_as_resolved() -> None:
    with pytest.raises(ValueError, match="only RESOLVED"):
        BlockingRelation(
            blocking_relation_id=BlockingRelationId(uuid4()),
            subject_physical_vehicle_id=PhysicalVehicleId(uuid4()),
            victim_physical_vehicle_id=PhysicalVehicleId(uuid4()),
            egress_zone_id=ZoneId(9),
            state=BlockingRelationState.CANCELED,
            observation=OBSERVED,
            confirm_trusted_seconds=0,
            clear_trusted_seconds=0,
            confirm_duration_seconds=0,
            clear_duration_seconds=0,
            record_version=1,
            created_at=NOW,
            updated_at=NOW,
            resolved_at=NOW,
            terminated_at=NOW,
            termination_reason="CANDIDATE_NOT_CONFIRMED",
        )


def test_backend_closed_does_not_imply_physical_exit() -> None:
    vehicle_id = PhysicalVehicleId(uuid4())
    mirror = ParkingSessionMirror(
        parking_session_id=101,
        administrative_state=SessionAdministrativeState.CLOSED,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.CAMERA_UNAVAILABLE,
            last_reliable_observed_at=NOW,
        ),
        context_revision=4,
        record_version=2,
        publication_revision=0,
        created_at=NOW,
        updated_at=NOW,
        physical_vehicle_id=vehicle_id,
    )

    assert mirror.administrative_state is SessionAdministrativeState.CLOSED
    assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
    assert mirror.physical_termination_origin is None


def test_allow_requires_authoritative_session_context() -> None:
    with pytest.raises(ValueError, match="authoritative context"):
        EntryMatchAttempt(
            entry_attempt_id=EntryAttemptId(uuid4()),
            match_state=EntryMatchState.PENDING,
            decision_state=EntryDecisionState.ALLOW,
            decision_revision=1,
            record_version=1,
            created_at=NOW,
            updated_at=NOW,
            match_deadline_at=NOW,
            authoritative_session_id=ParkingSessionId(10),
        )

    context = SessionContext(
        parking_session_id=ParkingSessionId(10),
        vehicle_id=VehicleId(20),
        is_electric=True,
        is_disabled_vehicle=False,
    )
    attempt = EntryMatchAttempt(
        entry_attempt_id=EntryAttemptId(uuid4()),
        match_state=EntryMatchState.PENDING,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=1,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
        match_deadline_at=NOW,
        authoritative_session_id=ParkingSessionId(10),
        authoritative_context=context,
    )

    assert attempt.authoritative_context == context


def test_non_exited_mirror_rejects_partial_exit_metadata() -> None:
    with pytest.raises(ValueError, match="must not carry"):
        ParkingSessionMirror(
            parking_session_id=ParkingSessionId(11),
            administrative_state=SessionAdministrativeState.ACTIVE,
            physical_presence_state=PhysicalPresenceState.INSIDE,
            physical_observation=OBSERVED,
            context_revision=1,
            record_version=1,
            publication_revision=0,
            created_at=NOW,
            updated_at=NOW,
            physical_vehicle_id=PhysicalVehicleId(uuid4()),
            physical_termination_origin=PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED,
            physical_exit_evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
        )


def test_unconfirmed_mirror_cannot_prebind_a_physical_vehicle() -> None:
    with pytest.raises(ValueError, match="UNCONFIRMED"):
        ParkingSessionMirror(
            parking_session_id=ParkingSessionId(12),
            administrative_state=SessionAdministrativeState.ACTIVE,
            physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
            physical_observation=OBSERVED,
            context_revision=0,
            record_version=1,
            publication_revision=0,
            created_at=NOW,
            updated_at=NOW,
            physical_vehicle_id=PhysicalVehicleId(uuid4()),
        )


def test_move_verification_requires_non_empty_targets() -> None:
    with pytest.raises(ValueError, match="at least one target"):
        MoveVerificationAttempt(
            request_id=MoveRequestId(1),
            verification_attempt=1,
            subject_physical_vehicle_id=PhysicalVehicleId(uuid4()),
            target_incident_ids=(),
            command_payload_hash="abc",
            state=MoveVerificationState.ACCEPTED,
            record_version=1,
            publication_revision=0,
            accepted_at=NOW,
            updated_at=NOW,
        )


@pytest.mark.parametrize(
    ("request_id", "verification_attempt"),
    [
        (MoveRequestId(BACKEND_LONG_MAX + 1), 1),
        (MoveRequestId(1), BACKEND_INTEGER_MAX + 1),
    ],
)
def test_move_verification_rejects_values_outside_backend_types(
    request_id: MoveRequestId,
    verification_attempt: int,
) -> None:
    with pytest.raises(ValueError, match="Backend type maximum"):
        MoveVerificationAttempt(
            request_id=request_id,
            verification_attempt=verification_attempt,
            subject_physical_vehicle_id=PhysicalVehicleId(uuid4()),
            target_incident_ids=(IncidentId(uuid4()),),
            command_payload_hash="abc",
            state=MoveVerificationState.ACCEPTED,
            record_version=1,
            publication_revision=0,
            accepted_at=NOW,
            updated_at=NOW,
        )


def test_move_verification_overall_result_is_derived_from_targets() -> None:
    incident_id = IncidentId(uuid4())
    with pytest.raises(ValueError, match="must be derived"):
        MoveVerificationAttempt(
            request_id=MoveRequestId(1),
            verification_attempt=1,
            subject_physical_vehicle_id=PhysicalVehicleId(uuid4()),
            target_incident_ids=(incident_id,),
            command_payload_hash="abc",
            state=MoveVerificationState.COMPLETED,
            record_version=1,
            publication_revision=1,
            accepted_at=NOW,
            updated_at=NOW,
            result=MoveVerificationResult.RESOLVED,
            incident_results=(
                MoveVerificationIncidentResult(
                    incident_id=incident_id,
                    result=MoveVerificationResult.STILL_ACTIVE,
                    incident_publication_revision=2,
                ),
            ),
            completed_at=NOW,
        )


def test_evicted_evidence_keeps_loss_metadata_without_file_path() -> None:
    artifact = EvidenceArtifact(
        evidence_id=EvidenceId(uuid4()),
        incident_id=IncidentId(uuid4()),
        captured_at=NOW,
        image_type="image/jpeg",
        state=EvidenceState.EVICTED,
        record_version=3,
        created_at=NOW,
        updated_at=NOW,
        publication_revision=1,
        byte_size=1234,
        checksum="sha256:abc",
        retention_disposition=EvidenceRetentionDisposition.STORAGE_PRESSURE,
        evicted_at=NOW,
    )

    assert artifact.local_path is None
    assert artifact.retention_disposition is EvidenceRetentionDisposition.STORAGE_PRESSURE

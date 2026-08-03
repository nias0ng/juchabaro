"""리플레이용 PublicationPreparer 계약 테스트(465/T-17).

`FrameObservationWorkflow._validate_prepared_publication`이 요구하는 envelope
4-tuple 일치와, JSONL 사이드 출력·결정론 식별자를 확인한다. 통합 경로는
`tests/application/test_replay_determinism.py`가 함께 지킨다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.application.frame_observation_workflow import _validate_prepared_publication
from src.application.physical_presence_workflow import SessionExitTransition
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    Incident,
    IncidentKey,
    IncidentKeyScope,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingTransition,
    ParkingTransitionType,
)
from src.replay.publication_preparer import (
    REPLAY_DESTINATION,
    JsonlPublicationPreparer,
    PublicationPreparerError,
)
from src.session.models import PhysicalExitEvidence, PhysicalTerminationOrigin

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
OBSERVED = ObservationStatus(state=ObservationState.OBSERVED, last_reliable_observed_at=T0)
EPISODE_ID = UUID(int=1)
VEHICLE_ID = UUID(int=2)
INCIDENT_ID = UUID(int=3)
FOOTPRINT = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))


def _parking_transition() -> ParkingTransition:
    return ParkingTransition(
        transition_type=ParkingTransitionType.PARKED,
        parking_episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=55,
        publication_revision=1,
        occurred_at=T0,
        assignment=ParkingAssignment(
            state=AssignmentState.ASSIGNED,
            representative_footprint=FOOTPRINT,
            confidence=0.9,
            last_stable_at=T0,
            zone_id=1,
        ),
    )


def _incident_transition() -> IncidentTransition:
    return IncidentTransition(
        transition_type=IncidentTransitionType.OPEN,
        incident=Incident(
            incident_id=INCIDENT_ID,
            key=IncidentKey(
                scope_type=IncidentKeyScope.ZONE_VISIT,
                scope_id=UUID(int=4),
                rule_code="RESTRICTED_ZONE",
            ),
            physical_vehicle_id=VEHICLE_ID,
            state=IncidentState.OPEN,
            observation=OBSERVED,
            confirm_trusted_seconds=1.0,
            clear_trusted_seconds=0.0,
            confirm_duration_seconds=0.0,
            clear_duration_seconds=0.0,
            record_version=1,
            publication_revision=1,
            first_observed_at=T0,
            created_at=T0,
            updated_at=T0,
            trusted_sample_max_gap_seconds=1.0,
            parking_session_id=55,
            zone_id=1,
            confirmed_at=T0,
        ),
    )


def _session_exit_transition() -> SessionExitTransition:
    return SessionExitTransition(
        parking_session_id=55,
        physical_vehicle_id=VEHICLE_ID,
        publication_revision=1,
        occurred_at=T0,
        origin=PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED,
        evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
    )


def test_parking_envelope_matches_what_the_workflow_validates():
    transition = _parking_transition()
    prepared = JsonlPublicationPreparer().prepare_parking(transition)

    # workflow가 실제로 부르는 검증기를 그대로 통과해야 한다.
    _validate_prepared_publication(
        prepared,
        aggregate_type="ParkingEpisode",
        aggregate_id=str(transition.parking_episode_id),
        publication_revision=transition.publication_revision,
        transition_type=transition.transition_type.value,
    )
    assert prepared.destination == REPLAY_DESTINATION
    assert prepared.delivery_id == prepared.idempotency_key


def test_incident_envelope_matches_what_the_workflow_validates():
    transition = _incident_transition()
    prepared = JsonlPublicationPreparer().prepare_incident(transition)

    _validate_prepared_publication(
        prepared,
        aggregate_type="Incident",
        aggregate_id=str(transition.incident.incident_id),
        publication_revision=transition.incident.publication_revision,
        transition_type=transition.transition_type.value,
    )
    payload = json.loads(prepared.payload.decode("utf-8"))
    assert payload["ruleCode"] == "RESTRICTED_ZONE"
    assert payload["firstObservedAt"] == T0.isoformat()


def test_session_exit_envelope_matches_what_the_workflow_validates():
    transition = _session_exit_transition()
    prepared = JsonlPublicationPreparer().prepare_session_exit(transition)

    _validate_prepared_publication(
        prepared,
        aggregate_type="ParkingSession",
        aggregate_id=str(transition.parking_session_id),
        publication_revision=transition.publication_revision,
        transition_type="SESSION_EXIT",
    )


def test_delivery_id_is_deterministic_across_instances():
    """새 인스턴스가 같은 전이에 같은 식별자를 준다 — uuid4()를 쓰지 않는다."""

    first = JsonlPublicationPreparer().prepare_parking(_parking_transition())
    second = JsonlPublicationPreparer().prepare_parking(_parking_transition())

    assert first == second
    assert first.delivery_id == "ParkingEpisode:%s:PARKED:1" % EPISODE_ID


def test_payload_is_written_to_the_events_handle_as_one_json_line(tmp_path):
    path = tmp_path / "events.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        preparer = JsonlPublicationPreparer(events_handle=handle)
        prepared = preparer.prepare_parking(_parking_transition())
        preparer.prepare_incident(_incident_transition())

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].encode("utf-8") == prepared.payload
    assert json.loads(lines[1])["aggregateType"] == "Incident"


def test_write_oserror_becomes_publication_preparer_error(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        monkeypatch.setattr(
            handle, "write", lambda line: (_ for _ in ()).throw(OSError("disk full"))
        )
        preparer = JsonlPublicationPreparer(events_handle=handle)

        with pytest.raises(PublicationPreparerError) as exc_info:
            preparer.prepare_parking(_parking_transition())

    assert exc_info.value.__cause__.__class__ is OSError

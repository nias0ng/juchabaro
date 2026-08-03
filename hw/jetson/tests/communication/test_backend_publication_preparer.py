"""API 6·7·10 canonical payload와 Incident 호환 mapping을 검증한다."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.application.physical_presence_workflow import SessionExitTransition
from src.communication.backend_publication_preparer import (
    BACKEND_DESTINATION,
    BackendPublicationPreparer,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentKeyScope,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingEpisodeId,
    ParkingTransition,
    ParkingTransitionType,
    ZoneId,
)
from src.session.models import (
    EntryAttemptId,
    PhysicalExitEvidence,
    PhysicalTerminationOrigin,
)
from src.tracking.models import ParkingSessionId, PhysicalVehicleId


KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 8, 1, 10, 0, 2, tzinfo=KST)
T1 = datetime(2026, 8, 1, 10, 0, 5, tzinfo=KST)
T2 = datetime(2026, 8, 1, 10, 8, 0, tzinfo=KST)
VEHICLE_ID = PhysicalVehicleId(
    UUID("b3a857d1-58ce-47d0-8899-33dc175aa201")
)
EPISODE_ID = ParkingEpisodeId(
    UUID("456c32e0-6c5c-47d3-9ca7-7597486735f0")
)
INCIDENT_ID = IncidentId(UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"))
SCOPE_ID = UUID("43c30b95-f2d0-4a17-a019-0f2a79d44a79")
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("d290f1ee-6c54-4b01-90e6-d701748f0852")
)


def test_prepare_parking_uses_api_6_contract_and_stable_identity() -> None:
    transition = ParkingTransition(
        transition_type=ParkingTransitionType.PARKED,
        parking_episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=ParkingSessionId(55),
        publication_revision=1,
        occurred_at=T1,
        assignment=ParkingAssignment(
            state=AssignmentState.ASSIGNED,
            representative_footprint=((0.1, 0.1), (0.2, 0.1), (0.2, 0.2)),
            confidence=0.9,
            last_stable_at=T1,
            zone_id=ZoneId(5),
        ),
    )

    prepared = BackendPublicationPreparer().prepare_parking(transition)

    assert prepared.destination == BACKEND_DESTINATION
    assert prepared.aggregate_type == "ParkingEpisode"
    assert prepared.aggregate_id == str(EPISODE_ID)
    assert prepared.delivery_id == f"ParkingEpisode:{EPISODE_ID}:1"
    assert prepared.idempotency_key == prepared.delivery_id
    assert json.loads(prepared.payload) == {
        "parkingEpisodeId": str(EPISODE_ID),
        "publicationRevision": 1,
        "transitionType": "PARKED",
        "physicalVehicleId": str(VEHICLE_ID),
        "sessionId": 55,
        "occurredAt": "2026-08-01T10:00:05+09:00",
        "assignment": {
            "state": "ASSIGNED",
            "zoneId": 5,
            "unassignedReason": None,
        },
    }
    assert BackendPublicationPreparer().prepare_parking(transition) == prepared


def test_prepare_unassigned_parking_omits_zone_id() -> None:
    transition = ParkingTransition(
        transition_type=ParkingTransitionType.PARKED,
        parking_episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=ParkingSessionId(55),
        publication_revision=1,
        occurred_at=T1,
        assignment=ParkingAssignment(
            state=AssignmentState.UNASSIGNED,
            representative_footprint=((0.1, 0.1), (0.2, 0.1), (0.2, 0.2)),
            confidence=0.5,
            last_stable_at=T1,
            unassigned_reason="NO_STABLE_ZONE",
        ),
    )

    assignment = json.loads(
        BackendPublicationPreparer().prepare_parking(transition).payload
    )["assignment"]

    assert assignment == {
        "state": "UNASSIGNED",
        "unassignedReason": "NO_STABLE_ZONE",
    }


@pytest.mark.parametrize(
    ("local_rule_code", "wire_rule_code"),
    [
        ("DISABLED_ZONE_UNAUTHORIZED", "DISABLED_ZONE_VIOLATION"),
        ("EV_ZONE_UNAUTHORIZED", "ETC"),
        ("EV_OVERSTAY", "EV_OVERSTAY"),
        ("BAD_PARKING", "BAD_PARKING"),
        ("DOUBLE_PARKING", "DOUBLE_PARKING"),
        ("OUT_OF_ZONE", "OUT_OF_ZONE"),
        ("AISLE_BLOCK", "ETC"),
    ],
)
def test_prepare_incident_maps_local_rule_code_for_api_7(
    local_rule_code: str,
    wire_rule_code: str,
) -> None:
    transition = _open_incident(local_rule_code)

    payload = json.loads(
        BackendPublicationPreparer().prepare_incident(transition).payload
    )

    assert payload["ruleCode"] == wire_rule_code
    assert payload["scope"]["type"] == transition.incident.key.scope_type.value
    assert payload["scope"]["id"] == str(transition.incident.key.scope_id)
    assert payload["entryAttemptId"] == str(ENTRY_ATTEMPT_ID)
    assert payload["sessionId"] == 55
    assert payload["occurredAt"] == "2026-08-01T10:00:05+09:00"
    assert payload["terminationReason"] is None


def test_prepare_incident_resolve_uses_resolution_fact() -> None:
    opened = _open_incident("EV_OVERSTAY").incident
    resolved = replace(
        opened,
        state=IncidentState.RESOLVED,
        publication_revision=2,
        record_version=2,
        updated_at=T2,
        resolved_at=T2,
        terminated_at=T2,
        termination_reason="ZONE_VISIT_ENDED",
    )

    payload = json.loads(
        BackendPublicationPreparer()
        .prepare_incident(
            IncidentTransition(
                transition_type=IncidentTransitionType.RESOLVE,
                incident=resolved,
            )
        )
        .payload
    )

    assert payload["publicationRevision"] == 2
    assert payload["transitionType"] == "RESOLVE"
    assert payload["occurredAt"] == "2026-08-01T10:08:00+09:00"
    assert payload["terminationReason"] == "ZONE_VISIT_ENDED"


def test_prepare_session_exit_uses_api_10_contract() -> None:
    prepared = BackendPublicationPreparer().prepare_session_exit(
        SessionExitTransition(
            parking_session_id=ParkingSessionId(55),
            physical_vehicle_id=VEHICLE_ID,
            publication_revision=1,
            occurred_at=T2,
            origin=PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED,
            evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
        )
    )

    assert prepared.aggregate_type == "ParkingSession"
    assert prepared.aggregate_id == "55"
    assert prepared.transition_type == "SESSION_EXIT"
    assert json.loads(prepared.payload) == {
        "sessionId": 55,
        "publicationRevision": 1,
        "physicalVehicleId": str(VEHICLE_ID),
        "occurredAt": "2026-08-01T10:08:00+09:00",
        "origin": "JETSON_EXIT_CONFIRMED",
        "evidence": "FULL_AREA_ABSENCE",
    }


def _open_incident(rule_code: str) -> IncidentTransition:
    scope_type = {
        "DISABLED_ZONE_UNAUTHORIZED": IncidentKeyScope.ZONE_VISIT,
        "EV_ZONE_UNAUTHORIZED": IncidentKeyScope.ZONE_VISIT,
        "EV_OVERSTAY": IncidentKeyScope.ZONE_VISIT,
        "BAD_PARKING": IncidentKeyScope.PHYSICAL_VEHICLE,
        "DOUBLE_PARKING": IncidentKeyScope.BLOCKING_RELATION,
        "OUT_OF_ZONE": IncidentKeyScope.PHYSICAL_VEHICLE,
        "AISLE_BLOCK": IncidentKeyScope.PHYSICAL_VEHICLE,
    }[rule_code]
    scope_id = UUID(str(VEHICLE_ID)) if (
        scope_type is IncidentKeyScope.PHYSICAL_VEHICLE
    ) else SCOPE_ID
    incident = Incident(
        incident_id=INCIDENT_ID,
        key=IncidentKey(
            scope_type=scope_type,
            scope_id=scope_id,
            rule_code=rule_code,
        ),
        physical_vehicle_id=VEHICLE_ID,
        state=IncidentState.OPEN,
        observation=ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=T1,
        ),
        confirm_trusted_seconds=3.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=3.0,
        clear_duration_seconds=3.0,
        record_version=1,
        publication_revision=1,
        first_observed_at=T0,
        created_at=T0,
        updated_at=T1,
        trusted_sample_max_gap_seconds=1.0,
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        parking_session_id=ParkingSessionId(55),
        zone_id=ZoneId(1),
        victim_physical_vehicle_id=(
            PhysicalVehicleId(
                UUID("c4b857d1-58ce-47d0-8899-33dc175aa202")
            )
            if rule_code == "DOUBLE_PARKING"
            else None
        ),
        confirmed_at=T1,
    )
    return IncidentTransition(
        transition_type=IncidentTransitionType.OPEN,
        incident=incident,
    )

"""API 6·7·10·12 domain transition을 Backend wire publication으로 확정한다.

이 adapter가 JSON field, ruleCode 호환 mapping, aggregate identity와
Idempotency-Key 형식을 소유한다. 한 번 반환한 payload bytes는 SQLite outbox에서
immutable하게 보존되며 retry 때 다시 직렬화하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from src.application.physical_presence_workflow import SessionExitTransition
from src.communication.backend_requests import MoveVerificationResultRequest
from src.communication.models import MoveVerificationAttempt, MoveVerificationState
from src.communication.outbox import PreparedPublication
from src.parking.models import (
    AssignmentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingTransition,
)


BACKEND_DESTINATION = "backend"

_INCIDENT_RULE_CODE_MAPPING: Mapping[str, str] = {
    "DISABLED_ZONE_UNAUTHORIZED": "DISABLED_ZONE_VIOLATION",
    # Backend enum 확장 전까지 최신 협의에 따라 두 rule을 ETC로 축약한다.
    "EV_ZONE_UNAUTHORIZED": "ETC",
    "EV_OVERSTAY": "EV_OVERSTAY",
    "BAD_PARKING": "BAD_PARKING",
    "DOUBLE_PARKING": "DOUBLE_PARKING",
    "OUT_OF_ZONE": "OUT_OF_ZONE",
    "AISLE_BLOCK": "ETC",
}
_INCIDENT_SCOPE_MAPPING = {
    "DISABLED_ZONE_UNAUTHORIZED": "ZONE_VISIT",
    "EV_ZONE_UNAUTHORIZED": "ZONE_VISIT",
    "EV_OVERSTAY": "ZONE_VISIT",
    "BAD_PARKING": "PHYSICAL_VEHICLE",
    "DOUBLE_PARKING": "BLOCKING_RELATION",
    "OUT_OF_ZONE": "PHYSICAL_VEHICLE",
    "AISLE_BLOCK": "PHYSICAL_VEHICLE",
}


class UnsupportedIncidentRuleCodeError(ValueError):
    """Backend와 mapping이 합의되지 않은 local Incident rule이다."""


class BackendPublicationPreparer:
    """API 6·7·10·12의 canonical JSON과 immutable publication identity를 만든다."""

    def prepare_parking(
        self,
        transition: ParkingTransition,
    ) -> PreparedPublication:
        """ParkingEpisode의 PARKED·UNPARKED 전이를 API 6 payload로 만든다."""

        payload = {
            "parkingEpisodeId": str(transition.parking_episode_id),
            "publicationRevision": transition.publication_revision,
            "transitionType": transition.transition_type.value,
            "physicalVehicleId": str(transition.physical_vehicle_id),
            "sessionId": int(transition.parking_session_id),
            "occurredAt": _timestamp(transition.occurred_at),
            "assignment": _parking_assignment(transition.assignment),
        }
        return _prepare(
            aggregate_type="ParkingEpisode",
            aggregate_id=str(transition.parking_episode_id),
            publication_revision=transition.publication_revision,
            transition_type=transition.transition_type.value,
            payload=payload,
        )

    def prepare_incident(
        self,
        transition: IncidentTransition,
    ) -> PreparedPublication:
        """Incident OPEN·RESOLVE 전이를 API 7 payload로 만든다."""

        incident = transition.incident
        if incident.parking_session_id is None:
            raise ValueError("Backend Incident publication requires sessionId")
        try:
            wire_rule_code = _INCIDENT_RULE_CODE_MAPPING[incident.key.rule_code]
        except KeyError as error:
            raise UnsupportedIncidentRuleCodeError(
                f"unsupported Incident ruleCode: {incident.key.rule_code}"
            ) from error
        expected_scope = _INCIDENT_SCOPE_MAPPING[incident.key.rule_code]
        if incident.key.scope_type.value != expected_scope:
            raise ValueError(
                f"{incident.key.rule_code} requires {expected_scope} scope"
            )
        if (
            incident.key.rule_code == "DOUBLE_PARKING"
            and incident.victim_physical_vehicle_id is None
        ):
            raise ValueError(
                "DOUBLE_PARKING requires victimPhysicalVehicleId"
            )

        if transition.transition_type is IncidentTransitionType.OPEN:
            occurred_at = incident.confirmed_at
            termination_reason = None
        else:
            occurred_at = incident.resolved_at
            termination_reason = incident.termination_reason
        if occurred_at is None:  # IncidentTransition invariant를 wire 경계에서도 방어한다.
            raise ValueError("Incident transition requires an occurredAt timestamp")

        payload = {
            "incidentId": str(incident.incident_id),
            "publicationRevision": incident.publication_revision,
            "transitionType": transition.transition_type.value,
            "physicalVehicleId": str(incident.physical_vehicle_id),
            "entryAttemptId": (
                str(incident.entry_attempt_id)
                if incident.entry_attempt_id is not None
                else None
            ),
            "sessionId": (
                int(incident.parking_session_id)
                if incident.parking_session_id is not None
                else None
            ),
            "ruleCode": wire_rule_code,
            "scope": {
                "type": incident.key.scope_type.value,
                "id": str(incident.key.scope_id),
            },
            "zoneId": int(incident.zone_id) if incident.zone_id is not None else None,
            "victimPhysicalVehicleId": (
                str(incident.victim_physical_vehicle_id)
                if incident.victim_physical_vehicle_id is not None
                else None
            ),
            "firstObservedAt": _timestamp(incident.first_observed_at),
            "occurredAt": _timestamp(occurred_at),
            "terminationReason": termination_reason,
        }
        return _prepare(
            aggregate_type="Incident",
            aggregate_id=str(incident.incident_id),
            publication_revision=incident.publication_revision,
            transition_type=transition.transition_type.value,
            payload=payload,
        )

    def prepare_session_exit(
        self,
        transition: SessionExitTransition,
    ) -> PreparedPublication:
        """Jetson이 확인한 물리 출차를 API 10 payload로 만든다."""

        payload = {
            "sessionId": int(transition.parking_session_id),
            "publicationRevision": transition.publication_revision,
            "physicalVehicleId": str(transition.physical_vehicle_id),
            "occurredAt": _timestamp(transition.occurred_at),
            "origin": transition.origin.value,
            "evidence": transition.evidence.value,
        }
        return _prepare(
            aggregate_type="ParkingSession",
            aggregate_id=str(int(transition.parking_session_id)),
            publication_revision=transition.publication_revision,
            transition_type="SESSION_EXIT",
            payload=payload,
        )

    def prepare_move_verification_result(
        self,
        attempt: MoveVerificationAttempt,
    ) -> PreparedPublication:
        """완료된 API 11 command의 immutable 결과를 API 12 payload로 만든다."""

        if attempt.state is not MoveVerificationState.COMPLETED:
            raise ValueError("MoveVerification publication requires COMPLETED state")
        if attempt.result is None or attempt.completed_at is None:
            raise ValueError("completed MoveVerification requires result timestamps")
        request = MoveVerificationResultRequest(
            request_id=int(attempt.request_id),
            verification_attempt=attempt.verification_attempt,
            publication_revision=attempt.publication_revision,
            result=attempt.result,
            incident_results=attempt.incident_results,
            completed_at=attempt.completed_at,
        )
        return _prepare(
            aggregate_type="MoveVerificationAttempt",
            aggregate_id=request.aggregate_id,
            publication_revision=request.publication_revision,
            transition_type="VERIFICATION_COMPLETED",
            payload=request.to_payload(),
        )


def _parking_assignment(assignment: ParkingAssignment) -> dict[str, object]:
    payload: dict[str, object] = {
        "state": assignment.state.value,
        "unassignedReason": assignment.unassigned_reason,
    }
    if assignment.state is AssignmentState.ASSIGNED:
        payload["zoneId"] = int(assignment.zone_id)
    return payload


def _prepare(
    *,
    aggregate_type: str,
    aggregate_id: str,
    publication_revision: int,
    transition_type: str,
    payload: Mapping[str, object],
) -> PreparedPublication:
    identity = f"{aggregate_type}:{aggregate_id}:{publication_revision}"
    return PreparedPublication(
        delivery_id=identity,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        destination=BACKEND_DESTINATION,
        publication_revision=publication_revision,
        transition_type=transition_type,
        payload=_canonical_json(payload),
        idempotency_key=identity,
    )


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _timestamp(value: datetime) -> str:
    return value.isoformat()

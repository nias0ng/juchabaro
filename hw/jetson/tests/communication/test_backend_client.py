"""Backend HW endpoint·header·공통 ACK 검증 테스트."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest

from src.communication.backend_client import (
    BackendClient,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.communication.backend_requests import (
    EvidenceUnavailableReason,
    EvidenceUnavailableRequest,
    EvidenceUploadRequest,
    MoveVerificationResultRequest,
)
from src.communication.models import (
    MoveVerificationIncidentResult,
    MoveVerificationResult,
)
from src.domain.models import DeliveryState
from src.parking.models import IncidentId
from src.storage.models import OutboxRecord, PublicationApplicationStatus


@pytest.mark.parametrize(
    (
        "aggregate_type",
        "transition_type",
        "expected_path",
        "expected_ack_aggregate_type",
    ),
    [
        (
            "ParkingEpisode",
            "PARKED",
            "/api/hw/parking/transitions",
            "ParkingEpisode",
        ),
        (
            "Incident",
            "OPEN",
            "/api/hw/parking-events/transitions",
            "Incident",
        ),
        (
            "ParkingSession",
            "SESSION_EXIT",
            "/api/hw/parking/exit",
            "Session",
        ),
    ],
)
def test_publish_routes_exact_bytes_and_validates_ack(
    aggregate_type: str,
    transition_type: str,
    expected_path: str,
    expected_ack_aggregate_type: str,
) -> None:
    publication = _publication(
        aggregate_type=aggregate_type,
        transition_type=transition_type,
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_ack(
                publication,
                aggregate_type=expected_ack_aggregate_type,
            ),
        )

    client = BackendClient(
        base_url="http://backend:8080/",
        hw_api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        confirmation = client.publish(publication)
    finally:
        client.close()

    assert len(captured) == 1
    assert captured[0].url.path == expected_path
    assert captured[0].content == publication.payload
    assert captured[0].headers["x-hw-api-key"] == "secret-key"
    assert captured[0].headers["idempotency-key"] == publication.idempotency_key
    assert captured[0].headers["content-type"] == "application/json"
    assert confirmation.application_status is PublicationApplicationStatus.APPLIED
    assert confirmation.payload_hash == publication.payload_hash
    assert confirmation.backend_correlation == {"eventId": 301}


def test_publish_accepts_ack_without_optional_payload_hash() -> None:
    publication = _publication()
    ack = _ack(publication)
    del ack["result"]["payloadHash"]
    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=ack)
        ),
    )
    try:
        confirmation = client.publish(publication)
    finally:
        client.close()

    assert confirmation.payload_hash == publication.payload_hash


def test_publish_treats_network_and_5xx_as_retryable() -> None:
    publication = _publication()

    def network_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    network_client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(network_error),
    )
    server_client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    )
    try:
        with pytest.raises(RetryableBackendPublicationError):
            network_client.publish(publication)
        with pytest.raises(RetryableBackendPublicationError, match="503"):
            server_client.publish(publication)
    finally:
        network_client.close()
        server_client.close()


def test_publish_accepts_already_applied_after_lost_ack() -> None:
    publication = _publication()
    ack = _ack(publication)
    ack["result"]["applicationResult"] = "ALREADY_APPLIED"
    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=ack)
        ),
    )
    try:
        confirmation = client.publish(publication)
    finally:
        client.close()

    assert (
        confirmation.application_status
        is PublicationApplicationStatus.ALREADY_APPLIED
    )


def test_publish_treats_4xx_and_mismatched_hash_as_terminal() -> None:
    publication = _publication()
    unauthorized_client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(lambda _: httpx.Response(401)),
    )
    bad_ack = _ack(publication)
    bad_ack["result"]["payloadHash"] = "sha256:" + ("0" * 64)
    mismatch_client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=bad_ack)
        ),
    )
    try:
        with pytest.raises(TerminalBackendPublicationError, match="401"):
            unauthorized_client.publish(publication)
        with pytest.raises(TerminalBackendPublicationError, match="payloadHash"):
            mismatch_client.publish(publication)
    finally:
        unauthorized_client.close()
        mismatch_client.close()


def test_upload_evidence_uses_multipart_contract() -> None:
    incident_id = UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91")
    evidence_id = UUID("7f4f9b5d-16c5-495f-8a91-bb7916f17e77")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_direct_ack(
                aggregate_type="EvidenceArtifact",
                aggregate_id=str(evidence_id),
                publication_revision=1,
            ),
        )

    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(handler),
    )
    try:
        confirmation = client.upload_evidence(
            EvidenceUploadRequest(
                incident_id=incident_id,
                evidence_id=evidence_id,
                publication_revision=1,
                content=b"\xff\xd8evidence\xff\xd9",
                captured_at=datetime(
                    2026,
                    8,
                    3,
                    10,
                    16,
                    5,
                    tzinfo=timezone(timedelta(hours=9)),
                ),
            ),
            idempotency_key="EvidenceArtifact:upload:1",
        )
    finally:
        client.close()

    sent = captured[0]
    assert sent.url.path == f"/api/hw/parking-events/{incident_id}/evidence"
    assert sent.headers["x-hw-api-key"] == "key"
    assert sent.headers["idempotency-key"] == "EvidenceArtifact:upload:1"
    assert sent.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"' in sent.content
    assert b'name="metadata"' in sent.content
    assert b"application/json" in sent.content
    assert b"evidenceId" in sent.content
    assert b"\xff\xd8evidence\xff\xd9" in sent.content
    assert confirmation.payload_hash is None


def test_publish_evidence_unavailable_uses_api_9_contract() -> None:
    incident_id = UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91")
    evidence_id = UUID("7f4f9b5d-16c5-495f-8a91-bb7916f17e77")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_direct_ack(
                aggregate_type="EvidenceArtifact",
                aggregate_id=str(evidence_id),
                publication_revision=1,
            ),
        )

    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(handler),
    )
    try:
        client.publish_evidence_unavailable(
            EvidenceUnavailableRequest(
                incident_id=incident_id,
                evidence_id=evidence_id,
                publication_revision=1,
                reason=EvidenceUnavailableReason.STORAGE_PRESSURE,
            ),
            idempotency_key="EvidenceArtifact:unavailable:1",
        )
    finally:
        client.close()

    sent = captured[0]
    assert sent.url.path == (
        f"/api/hw/parking-events/{incident_id}/evidence-unavailable"
    )
    assert sent.headers["x-hw-api-key"] == "key"
    assert sent.headers["idempotency-key"] == (
        "EvidenceArtifact:unavailable:1"
    )
    assert json.loads(sent.content) == {
        "evidenceId": str(evidence_id),
        "publicationRevision": 1,
        "reason": "STORAGE_PRESSURE",
        "unavailableAt": None,
        "byteSize": None,
        "checksum": None,
    }


def test_publish_move_verification_uses_api_12_contract() -> None:
    incident_id = IncidentId(
        UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91")
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_direct_ack(
                aggregate_type="MoveVerificationAttempt",
                aggregate_id="201:1",
                publication_revision=1,
            ),
        )

    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(handler),
    )
    try:
        client.publish_move_verification_result(
            MoveVerificationResultRequest(
                request_id=201,
                verification_attempt=1,
                publication_revision=1,
                result=MoveVerificationResult.RESOLVED,
                incident_results=(
                    MoveVerificationIncidentResult(
                        incident_id=incident_id,
                        result=MoveVerificationResult.RESOLVED,
                        incident_publication_revision=2,
                    ),
                ),
            ),
            idempotency_key="MoveVerificationAttempt:201:1:1",
        )
    finally:
        client.close()

    sent = captured[0]
    assert sent.url.path == "/api/hw/move-requests/201/verification"
    assert sent.headers["x-hw-api-key"] == "key"
    assert sent.headers["idempotency-key"] == (
        "MoveVerificationAttempt:201:1:1"
    )
    assert json.loads(sent.content) == {
        "verificationAttempt": 1,
        "publicationRevision": 1,
        "result": "RESOLVED",
        "incidentResults": [
            {
                "incidentId": str(incident_id),
                "result": "RESOLVED",
                "incidentPublicationRevision": 2,
            }
        ],
        "completedAt": None,
    }


def test_publish_routes_api_12_outbox_to_request_specific_path() -> None:
    payload = b'{"publicationRevision":1,"verificationAttempt":3}'
    publication = OutboxRecord(
        delivery_id="MoveVerificationAttempt:201:3:1",
        aggregate_type="MoveVerificationAttempt",
        aggregate_id="201:3",
        destination="backend",
        publication_revision=1,
        transition_type="VERIFICATION_COMPLETED",
        payload=payload,
        payload_hash=hashlib.sha256(payload).hexdigest(),
        idempotency_key="MoveVerificationAttempt:201:3:1",
        delivery_state=DeliveryState.IN_FLIGHT,
        attempt_count=1,
        next_attempt_at_us=None,
        last_error=None,
        created_at_us=1,
        updated_at_us=2,
        confirmed_at_us=None,
        record_version=2,
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ack(publication))

    client = BackendClient(
        base_url="http://backend:8080",
        hw_api_key="key",
        transport=httpx.MockTransport(handler),
    )
    try:
        client.publish(publication)
    finally:
        client.close()

    assert captured[0].url.path == "/api/hw/move-requests/201/verification"
    assert captured[0].content == payload
    assert captured[0].headers["idempotency-key"] == publication.idempotency_key


def _publication(
    *,
    aggregate_type: str = "Incident",
    transition_type: str = "OPEN",
) -> OutboxRecord:
    payload = b'{"immutable":true}'
    aggregate_id = "1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"
    return OutboxRecord(
        delivery_id=f"{aggregate_type}:{aggregate_id}:1",
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        destination="backend",
        publication_revision=1,
        transition_type=transition_type,
        payload=payload,
        payload_hash=hashlib.sha256(payload).hexdigest(),
        idempotency_key=f"{aggregate_type}:{aggregate_id}:1",
        delivery_state=DeliveryState.IN_FLIGHT,
        attempt_count=1,
        next_attempt_at_us=None,
        last_error=None,
        created_at_us=1,
        updated_at_us=2,
        confirmed_at_us=None,
        record_version=2,
    )


def _ack(
    publication: OutboxRecord,
    *,
    aggregate_type: str | None = None,
) -> dict[str, object]:
    return {
        "httpStatus": "OK",
        "isSuccess": True,
        "message": "전이가 적용되었습니다.",
        "code": 200,
        "result": {
            "aggregateType": aggregate_type or publication.aggregate_type,
            "aggregateId": publication.aggregate_id,
            "publicationRevision": publication.publication_revision,
            "applicationResult": "APPLIED",
            "payloadHash": f"sha256:{publication.payload_hash}",
            "backendCorrelation": {"eventId": 301},
        },
    }


def _direct_ack(
    *,
    aggregate_type: str,
    aggregate_id: str,
    publication_revision: int,
) -> dict[str, object]:
    return {
        "httpStatus": "OK",
        "isSuccess": True,
        "message": "적용되었습니다.",
        "code": 200,
        "result": {
            "aggregateType": aggregate_type,
            "aggregateId": aggregate_id,
            "publicationRevision": publication_revision,
            "applicationResult": "APPLIED",
            "backendCorrelation": {},
        },
    }

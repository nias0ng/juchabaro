"""API 6·7·10 endpoint·header·공통 ACK 검증 테스트."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from src.communication.backend_client import (
    BackendClient,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.domain.models import DeliveryState
from src.storage.models import OutboxRecord, PublicationApplicationStatus


@pytest.mark.parametrize(
    ("aggregate_type", "transition_type", "expected_path"),
    [
        ("ParkingEpisode", "PARKED", "/api/hw/parking/transitions"),
        ("Incident", "OPEN", "/api/hw/parking-events/transitions"),
        ("ParkingSession", "SESSION_EXIT", "/api/hw/parking/exit"),
    ],
)
def test_publish_routes_exact_bytes_and_validates_ack(
    aggregate_type: str,
    transition_type: str,
    expected_path: str,
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
            json=_ack(publication),
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


def _ack(publication: OutboxRecord) -> dict[str, object]:
    return {
        "httpStatus": "OK",
        "isSuccess": True,
        "message": "전이가 적용되었습니다.",
        "code": 200,
        "result": {
            "aggregateType": publication.aggregate_type,
            "aggregateId": publication.aggregate_id,
            "publicationRevision": publication.publication_revision,
            "applicationResult": "APPLIED",
            "payloadHash": f"sha256:{publication.payload_hash}",
            "backendCorrelation": {"eventId": 301},
        },
    }

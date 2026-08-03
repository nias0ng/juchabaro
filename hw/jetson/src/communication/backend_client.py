"""API 6·7·10 publication을 보내고 공통 적용 ACK를 검증한다.

HTTP 전송은 exact outbox payload bytes를 그대로 사용한다. 네트워크·5xx만
retryable로 분류하고, 4xx·계약 위반·payload 충돌은 운영 개입이 필요한 terminal
실패로 분리한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from src.communication.models import PublicationApplicationResult
from src.storage.models import OutboxRecord, PublicationApplicationStatus


_ENDPOINTS = {
    ("ParkingEpisode", "PARKED"): "/api/hw/parking/transitions",
    ("ParkingEpisode", "UNPARKED"): "/api/hw/parking/transitions",
    ("Incident", "OPEN"): "/api/hw/parking-events/transitions",
    ("Incident", "RESOLVE"): "/api/hw/parking-events/transitions",
    ("ParkingSession", "SESSION_EXIT"): "/api/hw/parking/exit",
}
_SHA256 = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class BackendPublicationError(RuntimeError):
    """Backend publication 전송 또는 ACK 검증 실패의 공통 기반."""


class RetryableBackendPublicationError(BackendPublicationError):
    """네트워크 또는 Backend 5xx로 다시 전송해도 되는 실패."""


class TerminalBackendPublicationError(BackendPublicationError):
    """요청·인증·계약·identity 충돌처럼 자동 retry하지 않을 실패."""


@dataclass(frozen=True, kw_only=True)
class PublicationConfirmation:
    """검증을 마친 Backend의 APPLIED·ALREADY_APPLIED 확인."""

    application_status: PublicationApplicationStatus
    payload_hash: str
    backend_correlation: Mapping[str, object]


class BackendClient:
    """API 6·7·10 endpoint와 outbound 적용 확인 계약을 소유한다."""

    def __init__(
        self,
        *,
        base_url: str,
        hw_api_key: str,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if not hw_api_key.strip():
            raise ValueError("hw_api_key must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._hw_api_key = hw_api_key
        self._client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
        )

    def publish(self, publication: OutboxRecord) -> PublicationConfirmation:
        """outbox의 exact bytes를 전송하고 aggregate ACK를 교차 검증한다."""

        endpoint = _ENDPOINTS.get(
            (publication.aggregate_type, publication.transition_type)
        )
        if endpoint is None:
            raise TerminalBackendPublicationError(
                "unsupported outbound publication: "
                f"{publication.aggregate_type}/{publication.transition_type}"
            )
        try:
            response = self._client.post(
                f"{self._base_url}{endpoint}",
                content=publication.payload,
                headers={
                    "Content-Type": "application/json",
                    "X-HW-API-Key": self._hw_api_key,
                    "Idempotency-Key": publication.idempotency_key,
                },
            )
        except httpx.RequestError as error:
            raise RetryableBackendPublicationError(
                f"Backend request failed: {type(error).__name__}"
            ) from error

        if response.status_code >= 500:
            raise RetryableBackendPublicationError(
                f"Backend returned HTTP {response.status_code}"
            )
        if not 200 <= response.status_code < 300:
            raise TerminalBackendPublicationError(
                f"Backend returned HTTP {response.status_code}"
            )
        return _parse_confirmation(response, publication)

    def close(self) -> None:
        """내부 connection pool을 닫는다."""

        self._client.close()


def _parse_confirmation(
    response: httpx.Response,
    publication: OutboxRecord,
) -> PublicationConfirmation:
    try:
        envelope = response.json()
    except (TypeError, ValueError) as error:
        raise TerminalBackendPublicationError(
            "Backend ACK is not valid JSON"
        ) from error
    if not isinstance(envelope, dict) or envelope.get("isSuccess") is not True:
        raise TerminalBackendPublicationError(
            "Backend ACK does not report a successful application"
        )
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise TerminalBackendPublicationError("Backend ACK result must be an object")

    try:
        application_result = PublicationApplicationResult(
            result.get("applicationResult")
        )
    except (TypeError, ValueError) as error:
        raise TerminalBackendPublicationError(
            "Backend ACK has an unknown applicationResult"
        ) from error
    if application_result is PublicationApplicationResult.CONFLICT:
        raise TerminalBackendPublicationError(
            "Backend reported a publication conflict"
        )
    if result.get("aggregateType") != publication.aggregate_type:
        raise TerminalBackendPublicationError(
            "Backend ACK aggregateType differs from the publication"
        )
    if str(result.get("aggregateId")) != publication.aggregate_id:
        raise TerminalBackendPublicationError(
            "Backend ACK aggregateId differs from the publication"
        )
    revision = result.get("publicationRevision")
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision != publication.publication_revision
    ):
        raise TerminalBackendPublicationError(
            "Backend ACK publicationRevision differs from the publication"
        )

    payload_hash_value = result.get("payloadHash")
    match = (
        _SHA256.fullmatch(payload_hash_value)
        if isinstance(payload_hash_value, str)
        else None
    )
    if match is None:
        raise TerminalBackendPublicationError(
            "Backend ACK payloadHash must use sha256:<hex>"
        )
    payload_hash = match.group(1).lower()
    if payload_hash != publication.payload_hash:
        raise TerminalBackendPublicationError(
            "Backend ACK payloadHash differs from the immutable publication"
        )

    correlation = result.get("backendCorrelation", {})
    if not isinstance(correlation, dict):
        raise TerminalBackendPublicationError(
            "Backend ACK backendCorrelation must be an object"
        )
    return PublicationConfirmation(
        application_status=PublicationApplicationStatus(application_result.value),
        payload_hash=payload_hash,
        backend_correlation=correlation,
    )

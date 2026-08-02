"""API DTO와 독립적인 local storage workflow record."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.models import DeliveryState


class PendingHandoffState(str, Enum):
    """외부 correlation을 기다리는 publication eligibility 상태."""

    WAITING_CORRELATION = "WAITING_CORRELATION"
    MATERIALIZED = "MATERIALIZED"
    EXPIRED = "EXPIRED"


class PublicationApplicationStatus(str, Enum):
    """Backend가 확인한 publication 적용 결과."""

    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass(frozen=True, kw_only=True)
class AcceptedInputRecord:
    """성공 응답 전에 영속한 inbound identity와 immutable payload."""

    input_type: str
    input_identity: str
    input_revision: int
    payload_hash: str
    request_payload: bytes
    workflow_state: str
    result_payload: bytes | None
    accepted_at_us: int
    updated_at_us: int
    record_version: int


@dataclass(frozen=True, kw_only=True)
class PendingHandoffRecord:
    """session correlation 전 domain 사실의 publication 대기 marker."""

    handoff_id: str
    aggregate_type: str
    aggregate_id: str
    transition_type: str
    original_occurred_at_us: int
    workflow_state: PendingHandoffState
    expires_at_us: int
    record_version: int
    created_at_us: int
    updated_at_us: int
    disposition_reason: str | None = None
    materialized_delivery_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class OutboxRecord:
    """retry 때 재직렬화하지 않는 한 publication의 immutable bytes."""

    delivery_id: str
    aggregate_type: str
    aggregate_id: str
    destination: str
    publication_revision: int
    transition_type: str
    payload: bytes
    payload_hash: str
    idempotency_key: str
    delivery_state: DeliveryState
    attempt_count: int
    next_attempt_at_us: int | None
    last_error: str | None
    created_at_us: int
    updated_at_us: int
    confirmed_at_us: int | None
    record_version: int


@dataclass(frozen=True, kw_only=True)
class DeliveryReceiptRecord:
    """DELIVERED outbox payload 축약 뒤 남기는 멱등 적용 증거."""

    delivery_id: str
    aggregate_type: str
    aggregate_id: str
    destination: str
    publication_revision: int
    payload_hash: str
    application_status: PublicationApplicationStatus
    confirmed_at_us: int
    expires_at_us: int
    backend_correlation_payload: bytes | None = None


@dataclass(frozen=True, kw_only=True)
class TombstoneRecord:
    """전체 lifecycle archive 대신 보존하는 terminal 최소 사실."""

    scope_type: str
    scope_id: str
    final_state: str
    occurred_at_us: int
    final_publication_revision: int
    expires_at_us: int
    created_at_us: int
    final_reason: str | None = None
    final_payload_hash: str | None = None
    backend_correlation_payload: bytes | None = None
    confirmed_at_us: int | None = None

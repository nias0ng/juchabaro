"""API DTO와 독립적인 local storage workflow record."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.domain.models import (
    DeliveryState,
    require_aware,
    require_non_negative,
    require_positive,
)
from src.parking.models import ZoneDefinitionVersion, ZoneId, ZoneVisitId
from src.tracking.models import PhysicalVehicleId


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
class ExitTraversalCheckpointRecord:
    """Workflow checkpoint for one active exit traversal per vehicle.

    This row is neither a public aggregate nor a publication source. It keeps
    an observed outward traversal durable after its ZoneVisit ends and across
    process restarts, until the physical-presence workflow consumes it.
    """

    physical_vehicle_id: PhysicalVehicleId
    exit_zone_id: ZoneId
    exit_zone_visit_id: ZoneVisitId
    zone_definition_version: ZoneDefinitionVersion
    outward_observed_at: datetime
    reentry_candidate_at: datetime | None
    reentry_trusted_seconds: float
    reentry_confirmation_seconds: float
    last_trusted_sample_at: datetime | None
    record_version: int
    updated_at: datetime

    def __post_init__(self) -> None:
        require_positive(self.exit_zone_id, "exit_zone_id")
        require_positive(
            self.zone_definition_version,
            "zone_definition_version",
        )
        require_non_negative(
            self.reentry_trusted_seconds,
            "reentry_trusted_seconds",
        )
        require_positive(
            self.reentry_confirmation_seconds,
            "reentry_confirmation_seconds",
        )
        if round(self.reentry_confirmation_seconds * 1_000_000) <= 0:
            raise ValueError(
                "reentry_confirmation_seconds must be at least one microsecond"
            )
        require_positive(self.record_version, "record_version")
        for name in (
            "outward_observed_at",
            "reentry_candidate_at",
            "last_trusted_sample_at",
            "updated_at",
        ):
            require_aware(getattr(self, name), name)

        trusted_duration_us = round(self.reentry_trusted_seconds * 1_000_000)
        if self.reentry_candidate_at is None and trusted_duration_us != 0:
            raise ValueError(
                "reentry trusted duration requires reentry_candidate_at"
            )
        if (
            self.reentry_candidate_at is None
            and self.last_trusted_sample_at is not None
        ):
            raise ValueError(
                "last_trusted_sample_at requires reentry_candidate_at"
            )
        if (
            self.reentry_candidate_at is not None
            and self.last_trusted_sample_at is None
        ):
            raise ValueError(
                "reentry candidate requires last_trusted_sample_at"
            )

        for name in (
            "reentry_candidate_at",
            "last_trusted_sample_at",
            "updated_at",
        ):
            value = getattr(self, name)
            if value is not None and value < self.outward_observed_at:
                raise ValueError(
                    f"{name} cannot precede outward_observed_at"
                )
        if (
            self.reentry_candidate_at is not None
            and self.last_trusted_sample_at is not None
            and self.last_trusted_sample_at < self.reentry_candidate_at
        ):
            raise ValueError(
                "last_trusted_sample_at cannot precede reentry_candidate_at"
            )
        if (
            self.last_trusted_sample_at is not None
            and self.updated_at < self.last_trusted_sample_at
        ):
            raise ValueError("updated_at cannot precede last_trusted_sample_at")


@dataclass(frozen=True, kw_only=True)
class AcceptedInputRecord:
    """성공 응답 전에 영속한 inbound identity와 immutable payload."""

    input_type: str
    input_identity: str
    input_revision: int
    idempotency_key: str | None
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

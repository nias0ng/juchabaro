"""Backend로 전송하는 evidence·verification wire 요청 DTO.

이 모듈은 API 8·9·13의 camelCase payload와 전송 전 계약 검증만 소유한다.
capture, spool 상태 전이, verification 실행과 outbox enqueue는 담당하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from src.communication.models import (
    MoveVerificationIncidentResult,
    MoveVerificationResult,
)


MEBIBYTE = 1024 * 1024
EVIDENCE_MAX_BYTES = 2 * MEBIBYTE
_SHA256 = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class EvidenceUnavailableReason(str, Enum):
    """Backend가 허용하는 evidence 제공 불가 사유."""

    RETENTION_EXPIRED = "RETENTION_EXPIRED"
    STORAGE_PRESSURE = "STORAGE_PRESSURE"
    LOST_OR_CORRUPTED = "LOST_OR_CORRUPTED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


@dataclass(frozen=True, kw_only=True)
class EvidenceUploadRequest:
    """API 8 multipart 업로드에 필요한 identity, metadata와 JPEG bytes."""

    incident_id: UUID
    evidence_id: UUID
    publication_revision: int
    content: bytes
    captured_at: datetime | None = None
    mime_type: str = "image/jpeg"
    byte_size: int | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.incident_id, "incident_id")
        _require_uuid(self.evidence_id, "evidence_id")
        _require_positive_int(
            self.publication_revision,
            "publication_revision",
        )
        if not isinstance(self.content, bytes):
            raise TypeError("content must be bytes")
        if not self.content:
            raise ValueError("content must not be empty")
        if len(self.content) > EVIDENCE_MAX_BYTES:
            raise ValueError("evidence content must not exceed 2MiB")
        if self.mime_type != "image/jpeg":
            raise ValueError("mime_type must be image/jpeg")
        _require_aware_optional(self.captured_at, "captured_at")

        if self.byte_size is not None:
            _require_non_negative_int(self.byte_size, "byte_size")
            if self.byte_size != len(self.content):
                raise ValueError("byte_size differs from evidence content")
        if self.checksum is not None:
            normalized = _normalize_checksum(self.checksum)
            if normalized != self.content_checksum:
                raise ValueError("checksum differs from evidence content")

    @property
    def content_checksum(self) -> str:
        return f"sha256:{hashlib.sha256(self.content).hexdigest()}"

    @property
    def filename(self) -> str:
        return f"{self.evidence_id}.jpg"

    def metadata_payload(self) -> dict[str, object]:
        return {
            "evidenceId": str(self.evidence_id),
            "publicationRevision": self.publication_revision,
            "capturedAt": _timestamp_or_none(self.captured_at),
            "mimeType": self.mime_type,
            "byteSize": len(self.content),
            "checksum": self.content_checksum,
        }


@dataclass(frozen=True, kw_only=True)
class EvidenceUnavailableRequest:
    """API 9 evidence 제공 불가 사실을 표현하는 JSON 요청."""

    incident_id: UUID
    evidence_id: UUID
    publication_revision: int
    reason: EvidenceUnavailableReason
    unavailable_at: datetime | None = None
    byte_size: int | None = None
    checksum: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.incident_id, "incident_id")
        _require_uuid(self.evidence_id, "evidence_id")
        _require_positive_int(
            self.publication_revision,
            "publication_revision",
        )
        if not isinstance(self.reason, EvidenceUnavailableReason):
            raise TypeError("reason must be EvidenceUnavailableReason")
        _require_aware_optional(self.unavailable_at, "unavailable_at")
        if self.byte_size is not None:
            _require_non_negative_int(self.byte_size, "byte_size")
        if self.checksum is not None:
            _normalize_checksum(self.checksum)

    def to_payload(self) -> dict[str, object]:
        return {
            "evidenceId": str(self.evidence_id),
            "publicationRevision": self.publication_revision,
            "reason": self.reason.value,
            "unavailableAt": _timestamp_or_none(self.unavailable_at),
            "byteSize": self.byte_size,
            "checksum": (
                None
                if self.checksum is None
                else _normalize_checksum(self.checksum)
            ),
        }


@dataclass(frozen=True, kw_only=True)
class MoveVerificationResultRequest:
    """API 12의 전체·Incident별 이동 확인 결과 JSON 요청."""

    request_id: int
    verification_attempt: int
    publication_revision: int
    result: MoveVerificationResult
    incident_results: tuple[MoveVerificationIncidentResult, ...] = ()
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_positive_int(self.request_id, "request_id")
        _require_positive_int(
            self.verification_attempt,
            "verification_attempt",
        )
        _require_positive_int(
            self.publication_revision,
            "publication_revision",
        )
        if not isinstance(self.result, MoveVerificationResult):
            raise TypeError("result must be MoveVerificationResult")
        if any(
            not isinstance(item, MoveVerificationIncidentResult)
            for item in self.incident_results
        ):
            raise TypeError(
                "incident_results must contain MoveVerificationIncidentResult"
            )
        _require_aware_optional(self.completed_at, "completed_at")

    @property
    def aggregate_id(self) -> str:
        return f"{self.request_id}:{self.verification_attempt}"

    def to_payload(self) -> dict[str, object]:
        return {
            "verificationAttempt": self.verification_attempt,
            "publicationRevision": self.publication_revision,
            "result": self.result.value,
            "incidentResults": [
                {
                    "incidentId": str(item.incident_id),
                    "result": item.result.value,
                    "incidentPublicationRevision": (
                        item.incident_publication_revision
                    ),
                }
                for item in self.incident_results
            ],
            "completedAt": _timestamp_or_none(self.completed_at),
        }


def canonical_json_bytes(payload: dict[str, object]) -> bytes:
    """멱등 재시도에 사용할 안정적인 UTF-8 JSON bytes를 만든다."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_aware_optional(value: datetime | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _timestamp_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _normalize_checksum(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("checksum must be string")
    match = _SHA256.fullmatch(value)
    if match is None:
        raise ValueError("checksum must use sha256:<hex>")
    return f"sha256:{match.group(1).lower()}"

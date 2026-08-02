"""Incident publication과 독립적으로 진행되는 evidence metadata 계약.

이미지 binary는 SQLite BLOB이 아니라 제한된 file spool에 둔다. 이 모델은
checksum·크기·로컬 파일 상태와 손실 사실만 영속하며 원본 CCTV 영상이나
durable ring buffer를 표현하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import NewType
from uuid import UUID

from src.domain.models import require_aware, require_non_negative, require_positive
from src.parking.models import IncidentId


EvidenceId = NewType("EvidenceId", UUID)


class EvidenceState(str, Enum):
    """capture 예약부터 전달·eviction까지의 metadata workflow."""

    RESERVED = "RESERVED"
    WRITING = "WRITING"
    READY = "READY"
    UPLOADING = "UPLOADING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EVICTION_PENDING = "EVICTION_PENDING"
    EVICTED = "EVICTED"
    FAILED = "FAILED"


class EvidenceRetentionDisposition(str, Enum):
    """binary가 현재 spool에 존재하지 않는 이유."""

    RETENTION_EXPIRED = "RETENTION_EXPIRED"
    STORAGE_PRESSURE = "STORAGE_PRESSURE"
    LOST_OR_CORRUPTED = "LOST_OR_CORRUPTED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


@dataclass(frozen=True, kw_only=True)
class EvidenceArtifact:
    """하나의 immutable evidence capture identity와 로컬 상태."""

    evidence_id: EvidenceId
    incident_id: IncidentId
    captured_at: datetime
    image_type: str
    state: EvidenceState
    record_version: int
    created_at: datetime
    updated_at: datetime
    publication_revision: int | None = None
    local_path: Path | None = None
    byte_size: int | None = None
    checksum: str | None = None
    last_error: str | None = None
    backend_acked_at: datetime | None = None
    retention_disposition: EvidenceRetentionDisposition | None = None
    evicted_at: datetime | None = None

    def __post_init__(self) -> None:
        require_positive(self.record_version, "record_version")
        for name in ("captured_at", "created_at", "updated_at", "backend_acked_at", "evicted_at"):
            require_aware(getattr(self, name), name)
        if not self.image_type:
            raise ValueError("image_type must not be empty")
        if self.publication_revision is not None:
            require_positive(self.publication_revision, "publication_revision")
        if self.byte_size is not None:
            require_non_negative(self.byte_size, "byte_size")

        has_complete_binary_metadata = (
            self.local_path is not None and self.byte_size is not None and self.checksum is not None
        )
        requires_binary_metadata = self.state in {
            EvidenceState.READY,
            EvidenceState.UPLOADING,
            EvidenceState.ACKNOWLEDGED,
            EvidenceState.EVICTION_PENDING,
        }
        if requires_binary_metadata and not has_complete_binary_metadata:
            raise ValueError(f"{self.state.value} evidence requires path, byte_size, and checksum")
        if self.state is EvidenceState.ACKNOWLEDGED and self.backend_acked_at is None:
            raise ValueError("ACKNOWLEDGED evidence requires backend_acked_at")
        if self.state is EvidenceState.EVICTED:
            if self.retention_disposition is None or self.evicted_at is None:
                raise ValueError("EVICTED evidence requires disposition and evicted_at")
            if self.local_path is not None:
                raise ValueError("EVICTED evidence must not reference a local file")
            if self.byte_size is None or self.checksum is None:
                raise ValueError("EVICTED evidence must retain byte_size and checksum")
        if self.state is EvidenceState.FAILED and not self.last_error:
            raise ValueError("FAILED evidence requires last_error")

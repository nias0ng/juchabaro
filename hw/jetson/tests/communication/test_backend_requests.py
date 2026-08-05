"""API 8·9·13 Backend request DTO의 wire payload 검증 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.communication.backend_requests import (
    EVIDENCE_MAX_BYTES,
    EvidenceUnavailableReason,
    EvidenceUnavailableRequest,
    EvidenceUploadRequest,
    MoveVerificationResultRequest,
)
from src.communication.models import (
    BACKEND_INTEGER_MAX,
    BACKEND_LONG_MAX,
    MoveVerificationIncidentResult,
    MoveVerificationResult,
)
from src.parking.models import IncidentId


KST = timezone(timedelta(hours=9))
CAPTURED_AT = datetime(2026, 8, 3, 10, 16, 5, tzinfo=KST)
INCIDENT_ID = UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91")
EVIDENCE_ID = UUID("7f4f9b5d-16c5-495f-8a91-bb7916f17e77")


def test_evidence_upload_derives_exact_metadata() -> None:
    content = b"\xff\xd8evidence\xff\xd9"
    request = EvidenceUploadRequest(
        incident_id=INCIDENT_ID,
        evidence_id=EVIDENCE_ID,
        publication_revision=1,
        content=content,
        captured_at=CAPTURED_AT,
    )

    assert request.metadata_payload() == {
        "evidenceId": str(EVIDENCE_ID),
        "publicationRevision": 1,
        "capturedAt": "2026-08-03T10:16:05+09:00",
        "mimeType": "image/jpeg",
        "byteSize": len(content),
        "checksum": request.content_checksum,
    }


def test_evidence_upload_rejects_size_and_checksum_mismatch() -> None:
    with pytest.raises(ValueError, match="2MiB"):
        EvidenceUploadRequest(
            incident_id=INCIDENT_ID,
            evidence_id=EVIDENCE_ID,
            publication_revision=1,
            content=b"x" * (EVIDENCE_MAX_BYTES + 1),
        )

    with pytest.raises(ValueError, match="checksum differs"):
        EvidenceUploadRequest(
            incident_id=INCIDENT_ID,
            evidence_id=EVIDENCE_ID,
            publication_revision=1,
            content=b"jpeg",
            checksum="sha256:" + ("0" * 64),
        )


def test_evidence_unavailable_uses_backend_reason_values() -> None:
    request = EvidenceUnavailableRequest(
        incident_id=INCIDENT_ID,
        evidence_id=EVIDENCE_ID,
        publication_revision=1,
        reason=EvidenceUnavailableReason.LOST_OR_CORRUPTED,
        unavailable_at=CAPTURED_AT,
        byte_size=123,
        checksum="sha256:" + ("a" * 64),
    )

    assert request.to_payload()["reason"] == "LOST_OR_CORRUPTED"
    assert request.to_payload()["unavailableAt"] == (
        "2026-08-03T10:16:05+09:00"
    )


def test_move_verification_builds_request_identity_and_results() -> None:
    incident_id = IncidentId(INCIDENT_ID)
    request = MoveVerificationResultRequest(
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
        completed_at=CAPTURED_AT,
    )

    assert request.aggregate_id == "201:1"
    assert request.to_payload()["incidentResults"] == [
        {
            "incidentId": str(INCIDENT_ID),
            "result": "RESOLVED",
            "incidentPublicationRevision": 2,
        }
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("request_id", BACKEND_LONG_MAX + 1),
        ("verification_attempt", BACKEND_INTEGER_MAX + 1),
    ],
)
def test_move_verification_rejects_values_outside_backend_types(
    field_name: str,
    value: int,
) -> None:
    arguments = {
        "request_id": 201,
        "verification_attempt": 1,
        "publication_revision": 1,
        "result": MoveVerificationResult.RESOLVED,
    }
    arguments[field_name] = value

    with pytest.raises(ValueError, match="Backend type maximum"):
        MoveVerificationResultRequest(**arguments)

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from src.communication.backend_client import BackendClient, BackendClientError
from src.communication.jetson_client import JetsonClient, JetsonClientError
from src.communication.schemas import (
    AcceptanceStatus,
    AccessDecision,
    BackendEntryRequest,
    BackendEntryResult,
    EntryMatchOutcome,
    EntryMatchState,
    JetsonEntryAcceptance,
    JetsonEntryRequest,
    SessionContext,
)


KST = timezone(timedelta(hours=9))
ENTRY_TIME = datetime(2026, 8, 1, 10, 0, tzinfo=KST)
ACCEPTED_AT = datetime(2026, 8, 1, 10, 0, 1, tzinfo=KST)
MATCHED_AT = datetime(2026, 8, 1, 10, 0, 5, tzinfo=KST)
MATCH_DEADLINE_AT = datetime(2026, 8, 1, 10, 0, 10, tzinfo=KST)
ENTRY_ATTEMPT_ID = "d290f1ee-6c54-4b01-90e6-d701748f0852"
PHYSICAL_VEHICLE_ID = "b3a857d1-58ce-47d0-8899-33dc175aa201"
IDEMPOTENCY_KEY = "8da5016b-6893-43f1-a996-42b4090be7f5"


def make_response(
    *,
    status: int,
    body: dict[str, object] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.getcode.return_value = status
    response.read.return_value = json.dumps(body or {}).encode("utf-8")
    return response


def success_envelope(
    result: dict[str, object],
    *,
    status: int,
) -> dict[str, object]:
    return {
        "httpStatus": "ACCEPTED" if status == 202 else "OK",
        "isSuccess": True,
        "message": "처리되었습니다.",
        "code": status,
        "result": result,
    }


def make_backend_request() -> BackendEntryRequest:
    return BackendEntryRequest(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
        ocr_confidence=0.98,
    )


def make_session_context() -> SessionContext:
    return SessionContext(
        session_id=55,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
    )


def make_backend_result(
    decision: AccessDecision = AccessDecision.ALLOW,
) -> BackendEntryResult:
    return BackendEntryResult(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        decision_revision=1,
        access_decision=decision,
        session_context=(
            make_session_context()
            if decision is AccessDecision.ALLOW
            else None
        ),
        duplicate_request=False,
    )


def test_backend_client_posts_api_1_and_parses_allow_result() -> None:
    response = make_response(
        status=201,
        body=success_envelope(
            {
                "entryAttemptId": ENTRY_ATTEMPT_ID,
                "decisionRevision": 1,
                "accessDecision": "ALLOW",
                "sessionContext": {
                    "sessionId": 55,
                    "vehicleId": 10,
                    "isDisabledVehicle": False,
                    "isElectric": True,
                },
                "duplicateRequest": False,
            },
            status=201,
        ),
    )
    client = BackendClient(
        "http://backend:8080/api",
        "backend-api-key",
        timeout_seconds=3.0,
    )

    with patch(
        "src.communication.backend_client.urlopen",
        return_value=response,
    ) as mocked_urlopen:
        result = client.request_entry(
            make_backend_request(),
            idempotency_key=IDEMPOTENCY_KEY,
        )

    sent_request = mocked_urlopen.call_args.args[0]
    sent_headers = {
        name.lower(): value for name, value in sent_request.header_items()
    }

    assert sent_request.full_url == "http://backend:8080/api/hw/parking/entry"
    assert sent_request.get_method() == "POST"
    assert sent_headers["x-hw-api-key"] == "backend-api-key"
    assert sent_headers["idempotency-key"] == IDEMPOTENCY_KEY
    assert json.loads(sent_request.data) == {
        "entryAttemptId": ENTRY_ATTEMPT_ID,
        "recognizedPlateNumber": "12가3456",
        "ocrConfidence": 0.98,
        "entryTime": "2026-08-01T10:00:00+09:00",
    }
    assert mocked_urlopen.call_args.kwargs["timeout"] == 3.0
    assert result == make_backend_result()


def test_backend_entry_request_omits_optional_ocr_confidence() -> None:
    request = BackendEntryRequest(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
    )

    assert "ocrConfidence" not in request.to_payload()


def test_backend_client_parses_review_without_session_context() -> None:
    response = make_response(
        status=200,
        body=success_envelope(
            {
                "entryAttemptId": ENTRY_ATTEMPT_ID,
                "decisionRevision": 1,
                "accessDecision": "REVIEW",
                "sessionContext": None,
                "duplicateRequest": True,
            },
            status=200,
        ),
    )
    client = BackendClient("http://backend:8080/api", "backend-api-key")

    with patch(
        "src.communication.backend_client.urlopen",
        return_value=response,
    ):
        result = client.request_entry(
            make_backend_request(),
            idempotency_key=IDEMPOTENCY_KEY,
        )

    assert result.access_decision is AccessDecision.REVIEW
    assert result.session_context is None
    assert result.duplicate_request is True


def test_backend_client_rejects_legacy_flat_result() -> None:
    response = make_response(
        status=201,
        body=success_envelope(
            {
                "accessDecision": "ALLOW",
                "trackingId": ENTRY_ATTEMPT_ID,
                "sessionId": 55,
                "vehicleId": 10,
            },
            status=201,
        ),
    )
    client = BackendClient("http://backend:8080/api", "backend-api-key")

    with (
        patch(
            "src.communication.backend_client.urlopen",
            return_value=response,
        ),
        pytest.raises(BackendClientError),
    ):
        client.request_entry(
            make_backend_request(),
            idempotency_key=IDEMPOTENCY_KEY,
        )


def test_backend_client_wraps_connection_failure() -> None:
    client = BackendClient("http://backend:8080/api", "backend-api-key")

    with (
        patch(
            "src.communication.backend_client.urlopen",
            side_effect=URLError("connection refused"),
        ),
        pytest.raises(BackendClientError),
    ):
        client.request_entry(
            make_backend_request(),
            idempotency_key=IDEMPOTENCY_KEY,
        )


def test_jetson_client_posts_api_2_and_parses_durable_acceptance() -> None:
    request = JetsonEntryRequest.from_backend(
        make_backend_request(),
        make_backend_result(),
    )
    response = make_response(
        status=202,
        body=success_envelope(
            {
                "entryAttemptId": ENTRY_ATTEMPT_ID,
                "decisionRevision": 1,
                "acceptanceStatus": "ACCEPTED",
                "matchState": "PENDING",
                "acceptedAt": "2026-08-01T10:00:01+09:00",
                "matchDeadlineAt": "2026-08-01T10:00:10+09:00",
            },
            status=202,
        ),
    )
    client = JetsonClient(
        "http://jetson:8000/",
        "jetson-api-key",
        timeout_seconds=3.0,
    )

    with patch(
        "src.communication.jetson_client.urlopen",
        return_value=response,
    ) as mocked_urlopen:
        result = client.send_entry(
            request,
            idempotency_key=IDEMPOTENCY_KEY,
        )

    sent_request = mocked_urlopen.call_args.args[0]
    sent_headers = {
        name.lower(): value for name, value in sent_request.header_items()
    }

    assert sent_request.full_url == "http://jetson:8000/internal/entry-events"
    assert sent_request.get_method() == "POST"
    assert sent_headers["x-internal-api-key"] == "jetson-api-key"
    assert sent_headers["idempotency-key"] == IDEMPOTENCY_KEY
    assert json.loads(sent_request.data) == {
        "entryAttemptId": ENTRY_ATTEMPT_ID,
        "decisionRevision": 1,
        "accessDecision": "ALLOW",
        "entryTime": "2026-08-01T10:00:00+09:00",
        "sessionContext": {
            "sessionId": 55,
            "vehicleId": 10,
            "isDisabledVehicle": False,
            "isElectric": True,
        },
    }
    assert mocked_urlopen.call_args.kwargs["timeout"] == 3.0
    assert result == JetsonEntryAcceptance(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        decision_revision=1,
        acceptance_status=AcceptanceStatus.ACCEPTED,
        match_state=EntryMatchState.PENDING,
        accepted_at=ACCEPTED_AT,
        match_deadline_at=MATCH_DEADLINE_AT,
    )


def test_jetson_request_for_deny_has_no_session_context() -> None:
    request = JetsonEntryRequest.from_backend(
        make_backend_request(),
        make_backend_result(AccessDecision.DENY),
    )

    assert request.to_payload()["sessionContext"] is None


def test_jetson_client_rejects_legacy_acceptance_response() -> None:
    request = JetsonEntryRequest.from_backend(
        make_backend_request(),
        make_backend_result(),
    )
    client = JetsonClient("http://jetson:8000", "jetson-api-key")

    with (
        patch(
            "src.communication.jetson_client.urlopen",
            return_value=make_response(status=202, body={"accepted": True}),
        ),
        pytest.raises(JetsonClientError),
    ):
        client.send_entry(request, idempotency_key=IDEMPOTENCY_KEY)


def test_jetson_client_gets_api_3_matched_outcome() -> None:
    response = make_response(
        status=200,
        body=success_envelope(
            {
                "entryAttemptId": ENTRY_ATTEMPT_ID,
                "decisionRevision": 1,
                "accessDecision": "ALLOW",
                "matchState": "MATCHED",
                "physicalVehicleId": PHYSICAL_VEHICLE_ID,
                "matchedAt": "2026-08-01T10:00:05+09:00",
                "terminalReason": None,
                "matchDeadlineAt": "2026-08-01T10:00:10+09:00",
            },
            status=200,
        ),
    )
    client = JetsonClient(
        "http://jetson:8000",
        "jetson-api-key",
        timeout_seconds=3.0,
    )

    with patch(
        "src.communication.jetson_client.urlopen",
        return_value=response,
    ) as mocked_urlopen:
        result = client.get_entry_match_outcome(ENTRY_ATTEMPT_ID)

    sent_request = mocked_urlopen.call_args.args[0]
    sent_headers = {
        name.lower(): value for name, value in sent_request.header_items()
    }

    assert sent_request.full_url == (
        "http://jetson:8000/internal/entry-events/"
        f"{ENTRY_ATTEMPT_ID}"
    )
    assert sent_request.get_method() == "GET"
    assert sent_headers["x-internal-api-key"] == "jetson-api-key"
    assert "idempotency-key" not in sent_headers
    assert mocked_urlopen.call_args.kwargs["timeout"] == 3.0
    assert result == EntryMatchOutcome(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        decision_revision=1,
        access_decision=AccessDecision.ALLOW,
        match_state=EntryMatchState.MATCHED,
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        matched_at=MATCHED_AT,
        terminal_reason=None,
        match_deadline_at=MATCH_DEADLINE_AT,
    )


def test_jetson_client_gets_api_3_expired_outcome() -> None:
    response = make_response(
        status=200,
        body=success_envelope(
            {
                "entryAttemptId": ENTRY_ATTEMPT_ID,
                "decisionRevision": 1,
                "accessDecision": "REVIEW",
                "matchState": "EXPIRED",
                "physicalVehicleId": None,
                "matchedAt": None,
                "terminalReason": "MATCH_DEADLINE_EXCEEDED",
                "matchDeadlineAt": "2026-08-01T10:00:10+09:00",
            },
            status=200,
        ),
    )
    client = JetsonClient("http://jetson:8000", "jetson-api-key")

    with patch(
        "src.communication.jetson_client.urlopen",
        return_value=response,
    ):
        result = client.get_entry_match_outcome(ENTRY_ATTEMPT_ID)

    assert result.match_state is EntryMatchState.EXPIRED
    assert result.physical_vehicle_id is None
    assert result.terminal_reason == "MATCH_DEADLINE_EXCEEDED"


def test_jetson_client_wraps_connection_failure() -> None:
    request = JetsonEntryRequest.from_backend(
        make_backend_request(),
        make_backend_result(AccessDecision.DENY),
    )
    client = JetsonClient("http://jetson:8000", "jetson-api-key")

    with (
        patch(
            "src.communication.jetson_client.urlopen",
            side_effect=URLError("connection refused"),
        ),
        pytest.raises(JetsonClientError),
    ):
        client.send_entry(request, idempotency_key=IDEMPOTENCY_KEY)

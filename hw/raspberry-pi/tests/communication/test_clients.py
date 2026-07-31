import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from src.communication.backend_client import BackendClient, BackendClientError
from src.communication.jetson_client import JetsonClient, JetsonClientError
from src.communication.schemas import (
    AccessDecision,
    BackendEntryRequest,
    BackendEntryResult,
    JetsonEntryRequest,
)


ENTRY_TIME = datetime(
    2026,
    7,
    31,
    9,
    30,
    tzinfo=timezone(timedelta(hours=9)),
)
TRACKING_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
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


def test_backend_client_posts_entry_and_parses_allow_result() -> None:
    response = make_response(
        status=201,
        body={
            "httpStatus": "CREATED",
            "isSuccess": True,
            "message": "입차가 허용되었습니다.",
            "code": 201,
            "result": {
                "accessDecision": "ALLOW",
                "registered": True,
                "vehicleId": 10,
                "isDisabledVehicle": False,
                "isElectric": True,
                "vehicleStatus": "ACTIVE",
                "trackingId": TRACKING_ID,
                "sessionId": 55,
                "duplicateRequest": False,
            },
        },
    )
    request = BackendEntryRequest(
        tracking_id=TRACKING_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
        ocr_confidence=0.98,
    )
    client = BackendClient(
        "http://backend:8080",
        "backend-api-key",
        timeout_seconds=3.0,
    )

    with patch(
        "src.communication.backend_client.urlopen",
        return_value=response,
    ) as mocked_urlopen:
        result = client.request_entry(
            request,
            idempotency_key=IDEMPOTENCY_KEY,
        )

    sent_request = mocked_urlopen.call_args.args[0]
    sent_headers = {
        name.lower(): value
        for name, value in sent_request.header_items()
    }

    assert sent_request.full_url == (
        "http://backend:8080/hw/parking/entry"
    )
    assert sent_request.get_method() == "POST"
    assert sent_headers["x-hw-api-key"] == "backend-api-key"
    assert sent_headers["idempotency-key"] == IDEMPOTENCY_KEY
    assert json.loads(sent_request.data) == {
        "trackingId": TRACKING_ID,
        "recognizedPlateNumber": "12가3456",
        "entryTime": "2026-07-31T09:30:00+09:00",
        "ocrConfidence": 0.98,
    }
    assert mocked_urlopen.call_args.kwargs["timeout"] == 3.0
    assert result == BackendEntryResult(
        access_decision=AccessDecision.ALLOW,
        registered=True,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
        vehicle_status="ACTIVE",
        tracking_id=TRACKING_ID,
        session_id=55,
        duplicate_request=False,
    )


def test_backend_client_wraps_connection_failure() -> None:
    client = BackendClient("http://backend:8080", "backend-api-key")
    request = BackendEntryRequest(
        tracking_id=TRACKING_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
    )

    with (
        patch(
            "src.communication.backend_client.urlopen",
            side_effect=URLError("connection refused"),
        ),
        pytest.raises(BackendClientError),
    ):
        client.request_entry(
            request,
            idempotency_key=IDEMPOTENCY_KEY,
        )


def test_jetson_client_posts_backend_result_as_entry_event() -> None:
    backend_request = BackendEntryRequest(
        tracking_id=TRACKING_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
    )
    backend_result = BackendEntryResult(
        access_decision=AccessDecision.ALLOW,
        registered=True,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
        vehicle_status="ACTIVE",
        tracking_id=TRACKING_ID,
        session_id=55,
        duplicate_request=False,
    )
    request = JetsonEntryRequest.from_backend(
        backend_request,
        backend_result,
    )
    client = JetsonClient(
        "http://jetson:8000/",
        "jetson-api-key",
        timeout_seconds=3.0,
    )

    with patch(
        "src.communication.jetson_client.urlopen",
        return_value=make_response(status=202),
    ) as mocked_urlopen:
        result = client.send_entry(
            request,
            idempotency_key=IDEMPOTENCY_KEY,
        )

    sent_request = mocked_urlopen.call_args.args[0]
    sent_headers = {
        name.lower(): value
        for name, value in sent_request.header_items()
    }

    assert result is None
    assert sent_request.full_url == (
        "http://jetson:8000/internal/entry-events"
    )
    assert sent_request.get_method() == "POST"
    assert sent_headers["x-internal-api-key"] == "jetson-api-key"
    assert sent_headers["idempotency-key"] == IDEMPOTENCY_KEY
    assert json.loads(sent_request.data) == {
        "trackingId": TRACKING_ID,
        "recognizedPlateNumber": "12가3456",
        "entryTime": "2026-07-31T09:30:00+09:00",
        "accessDecision": "ALLOW",
        "registered": True,
        "vehicleId": 10,
        "isDisabledVehicle": False,
        "isElectric": True,
        "vehicleStatus": "ACTIVE",
        "sessionId": 55,
        "duplicateRequest": False,
    }
    assert mocked_urlopen.call_args.kwargs["timeout"] == 3.0


def test_jetson_client_wraps_connection_failure() -> None:
    client = JetsonClient("http://jetson:8000", "jetson-api-key")
    request = JetsonEntryRequest(
        tracking_id=TRACKING_ID,
        recognized_plate_number="12가3456",
        entry_time=ENTRY_TIME,
        access_decision=AccessDecision.DENY,
        registered=False,
        vehicle_id=None,
        is_disabled_vehicle=None,
        is_electric=None,
        vehicle_status=None,
        session_id=None,
        duplicate_request=False,
    )

    with (
        patch(
            "src.communication.jetson_client.urlopen",
            side_effect=URLError("connection refused"),
        ),
        pytest.raises(JetsonClientError),
    ):
        client.send_entry(
            request,
            idempotency_key=IDEMPOTENCY_KEY,
        )

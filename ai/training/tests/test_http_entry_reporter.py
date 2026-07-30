import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from http_entry_reporter import EntryReportError, HttpEntryReporter, _idempotency_key


def _mock_response(status: int = 200, body: dict | None = None):
    if body is None:
        body = {
            "httpStatus": "CREATED",
            "isSuccess": True,
            "message": "입차가 허용되었습니다.",
            "code": 201,
            "result": {
                "accessDecision": "ALLOW",
                "registered": True,
                "vehicleId": 42,
                "isDisabledVehicle": False,
                "isElectric": False,
                "vehicleStatus": "ACTIVE",
                "trackingId": "7",
                "sessionId": 100,
                "duplicateRequest": False,
            },
        }
    response = MagicMock()
    response.status = status
    response.read.return_value = json.dumps(body, ensure_ascii=False).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_report_entry_sends_expected_payload_and_headers():
    reporter = HttpEntryReporter(base_url="http://jetson.local:8080/", api_key="secret-key")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time, ocr_confidence=0.92)

    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "http://jetson.local:8080/hw/parking/entry"
    assert request.get_method() == "POST"
    assert request.get_header("X-hw-api-key") == "secret-key"
    assert request.get_header("Content-type") == "application/json; charset=utf-8"
    assert request.get_header("Idempotency-key") == _idempotency_key(7, "12가3456", entry_time)

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["trackingId"] == "7"
    assert payload["recognizedPlateNumber"] == "12가3456"
    assert payload["ocrConfidence"] == 0.92
    assert payload["entryTime"] == entry_time.isoformat()


def test_report_entry_parses_allow_response():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response(status=201)):
        result = reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)

    assert result.access_decision == "ALLOW"
    assert result.registered is True
    assert result.vehicle_id == 42
    assert result.session_id == 100
    assert result.duplicate_request is False


def test_report_entry_parses_deny_response():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    body = {
        "httpStatus": "OK",
        "isSuccess": True,
        "message": "입차가 거부되었습니다.",
        "code": 200,
        "result": {
            "accessDecision": "DENY",
            "registered": False,
            "vehicleId": None,
            "isDisabledVehicle": None,
            "isElectric": None,
            "vehicleStatus": None,
            "trackingId": "9",
            "sessionId": None,
            "duplicateRequest": False,
        },
    }
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response(status=200, body=body)):
        result = reporter.report_entry(track_id=9, plate_number="99미9999", entry_time=entry_time)

    # DENY는 실패가 아니라 정상 응답이므로 예외 없이 반환되어야 한다.
    assert result.access_decision == "DENY"
    assert result.registered is False
    assert result.vehicle_id is None


def test_report_entry_parses_review_response():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    body = {
        "httpStatus": "OK",
        "isSuccess": True,
        "message": "차량 확인이 필요합니다.",
        "code": 200,
        "result": {
            "accessDecision": "REVIEW",
            "registered": True,
            "vehicleId": 42,
            "isDisabledVehicle": False,
            "isElectric": False,
            "vehicleStatus": "ACTIVE",
            "trackingId": "7",
            "sessionId": None,
            "duplicateRequest": False,
        },
    }
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response(status=200, body=body)):
        result = reporter.report_entry(track_id=7, plate_number="12가3457", entry_time=entry_time)

    assert result.access_decision == "REVIEW"
    assert result.session_id is None


def test_idempotency_key_is_deterministic_for_same_event():
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    key_a = _idempotency_key(7, "12가3456", entry_time)
    key_b = _idempotency_key(7, "12가3456", entry_time)
    assert key_a == key_b


def test_idempotency_key_differs_for_different_events():
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    key_a = _idempotency_key(7, "12가3456", entry_time)
    key_b = _idempotency_key(8, "12가3456", entry_time)
    assert key_a != key_b


def test_report_entry_raises_http_report_error_on_http_error():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    error = HTTPError(url="http://jetson.local/hw/parking/entry", code=400, msg="Bad Request", hdrs=None, fp=None)

    with patch("http_entry_reporter.urllib_request.urlopen", side_effect=error):
        with pytest.raises(EntryReportError):
            reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)


def test_report_entry_raises_http_report_error_on_connection_failure():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(EntryReportError):
            reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)


def test_report_entry_raises_when_backend_reports_failure():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    body = {"httpStatus": "UNAUTHORIZED", "isSuccess": False, "message": "인증 실패", "code": 401, "result": None}

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response(status=200, body=body)):
        with pytest.raises(EntryReportError):
            reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)


def test_report_entry_raises_on_non_success_status_without_exception():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=_mock_response(status=305)):
        with pytest.raises(EntryReportError):
            reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)


def test_report_entry_raises_on_malformed_json():
    reporter = HttpEntryReporter(base_url="http://jetson.local", api_key="k")
    entry_time = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    response = MagicMock()
    response.status = 200
    response.read.return_value = b"not json"
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)

    with patch("http_entry_reporter.urllib_request.urlopen", return_value=response):
        with pytest.raises(EntryReportError):
            reporter.report_entry(track_id=7, plate_number="12가3456", entry_time=entry_time)

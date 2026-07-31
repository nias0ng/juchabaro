import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from http_result_publisher import DEFAULT_STATUS_TO_EVENT_TYPE, HttpPublishError, HttpResultPublisher
from jetson_vehicle_tracking_baseline import ViolationEvent, ViolationStatus, ZoneType


def _make_event(**overrides) -> ViolationEvent:
    defaults = dict(
        track_id=7,
        plate_number="12가3456",
        status=ViolationStatus.DOUBLE_PARK,
        # zone_id는 백엔드가 발급하는 기계 식별자(Long)이고, 사람이 읽는 구역 번호는
        # zone_number다. 페이로드에는 계약대로 zone_id만 실린다.
        zone_id=12,
        zone_number="GEN-01",
        zone_type=ZoneType.GENERAL,
        overlap_ratio=0.375,
        dwell_seconds=650.0,
        occupancy_seconds=650.0,
        detected_at=datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return ViolationEvent(**defaults)


def _mock_response(status: int = 200):
    response = MagicMock()
    response.status = status
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_publish_sends_expected_payload_and_headers():
    publisher = HttpResultPublisher(base_url="http://jetson.local:8080/", api_key="secret-key")
    event = _make_event()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "http://jetson.local:8080/api/hw/parking-events"
    assert request.get_method() == "POST"
    assert request.get_header("X-hw-api-key") == "secret-key"
    assert request.get_header("Content-type") == "application/json; charset=utf-8"

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["trackingId"] == 7
    assert payload["plateNumber"] == "12가3456"
    assert payload["zoneId"] == 12
    assert payload["eventType"] == "DOUBLE_PARKING"
    assert payload["detectedAt"] == "2026-07-30T12:00:00+00:00"


def test_publish_converts_overlap_ratio_to_rounded_percentage():
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k")
    event = _make_event(overlap_ratio=0.375)

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["violationRatio"] == 38  # 0.375 * 100 = 37.5 -> round-half-to-even
    assert isinstance(payload["violationRatio"], int)


def test_publish_skips_and_warns_when_plate_number_is_none():
    """번호판 매칭 실패(PLATE_UNMATCHED) 이벤트는 백엔드 vehicle_id NOT NULL 제약 때문에
    전송을 건너뛴다 — 크래시하지 않고 조용히 스킵되는 것만 확인한다."""
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k")
    event = _make_event(plate_number=None)

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        publisher.publish(event)

    mock_urlopen.assert_not_called()


def test_publish_raises_when_status_has_no_mapping():
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k", status_to_event_type={})
    event = _make_event()

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        with pytest.raises(HttpPublishError):
            publisher.publish(event)
    mock_urlopen.assert_not_called()


def test_publish_raises_http_publish_error_on_http_error():
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k")
    event = _make_event()
    error = HTTPError(url="http://jetson.local/api/hw/parking-events", code=400, msg="Bad Request", hdrs=None, fp=None)

    with patch("http_result_publisher.urllib_request.urlopen", side_effect=error):
        with pytest.raises(HttpPublishError):
            publisher.publish(event)


def test_publish_raises_http_publish_error_on_connection_failure():
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k")
    event = _make_event()

    with patch("http_result_publisher.urllib_request.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(HttpPublishError):
            publisher.publish(event)


def test_publish_raises_http_publish_error_on_non_success_status_without_exception():
    """urllib은 보통 4xx/5xx에서 HTTPError를 스스로 던지지만, 그러지 않는 경우(예: 3xx
    리다이렉트가 안 따라가진 경우)를 대비한 방어 코드도 확인한다."""
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k")
    event = _make_event()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response(status=305)):
        with pytest.raises(HttpPublishError):
            publisher.publish(event)


def test_custom_status_to_event_type_mapping_overrides_default():
    custom_mapping = dict(DEFAULT_STATUS_TO_EVENT_TYPE)
    custom_mapping["DOUBLE_PARK"] = "CUSTOM_TYPE"
    publisher = HttpResultPublisher(base_url="http://jetson.local", api_key="k", status_to_event_type=custom_mapping)
    event = _make_event(status=ViolationStatus.DOUBLE_PARK)

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["eventType"] == "CUSTOM_TYPE"


def test_default_mapping_covers_every_violation_status_except_none_and_observing():
    """새 ViolationStatus가 추가됐는데 매핑을 안 넣으면 조용히 실패하는 대신, 이 테스트가
    먼저 잡아내도록 한다."""
    reportable_statuses = {
        status for status in ViolationStatus if status not in (ViolationStatus.NONE, ViolationStatus.OBSERVING)
    }
    assert set(DEFAULT_STATUS_TO_EVENT_TYPE.keys()) == {status.value for status in reportable_statuses}

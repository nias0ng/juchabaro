import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest
from http_result_publisher import (
    DEFAULT_STATUS_TO_EVENT_TYPE,
    DEFAULT_STATUS_TO_REASON,
    HttpPublishError,
    HttpResultPublisher,
)
from jetson_vehicle_tracking_baseline import ViolationEvent, ViolationStatus, ZoneType


def _make_event(**overrides) -> ViolationEvent:
    defaults = dict(
        track_id=7,
        plate_number="12가3456",
        status=ViolationStatus.DOUBLE_PARK,
        # zone_id/zone_number/plate_number는 판정 결과에는 남지만 명세의
        # parking-events 요청 스키마에는 없어 payload로 나가지 않는다.
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


def _mock_response(status: int = 201):
    response = MagicMock()
    response.status = status
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def _images(_event):
    return [
        {
            "imageUrl": "https://storage.example.com/events/parking-1001.jpg",
            "imageType": "PARKING_STATE",
            "capturedAt": datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc),
        }
    ]


def _publisher(**overrides) -> HttpResultPublisher:
    """명세 필수 필드를 모두 채울 수 있는, 전송이 실제로 일어나는 publisher."""

    kwargs = dict(
        base_url="http://backend.local:8080/",
        api_key="secret-key",
        session_id_resolver=lambda _event: 1001,
        image_supplier=_images,
    )
    kwargs.update(overrides)
    return HttpResultPublisher(**kwargs)


def test_publish_sends_spec_payload_and_headers():
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(_make_event())

    assert mock_urlopen.call_count == 1
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "http://backend.local:8080/api/hw/parking-events"
    assert request.get_method() == "POST"
    assert request.get_header("X-hw-api-key") == "secret-key"
    assert request.get_header("Content-type") == "application/json; charset=utf-8"

    payload = json.loads(request.data.decode("utf-8"))
    assert payload["sessionId"] == 1001
    assert payload["eventType"] == "DOUBLE_PARKING"
    assert payload["images"] == [
        {
            "imageUrl": "https://storage.example.com/events/parking-1001.jpg",
            "imageType": "PARKING_STATE",
            "capturedAt": "2026-07-30T21:00:00+09:00",
        }
    ]


def test_publish_omits_fields_absent_from_the_spec():
    """이전 구현이 보내던 trackingId/plateNumber/zoneId는 명세 요청 스키마에 없다.

    특히 trackingId는 명세에서 RPi가 발급하는 방문 UUID(문자열)인데 구현은 YOLO
    트래커 정수 ID를 담고 있었다 — 같은 이름에 다른 의미가 실려 나가지 않도록 한다.
    """
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(_make_event())

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert set(payload) == {"sessionId", "eventType", "reason", "violationRatio", "detectedAt", "images"}


def test_publish_sends_detected_at_in_kst():
    """백엔드 ParkingEvent.detectedAt이 offset 없는 LocalDateTime이라, UTC로 보내면
    offset이 떨어지는 순간 9시간 이른 시각이 저장된다."""
    publisher = _publisher()
    event = _make_event(detected_at=datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc))

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["detectedAt"] == "2026-07-30T21:00:00+09:00"


def test_publish_rejects_naive_detected_at():
    publisher = _publisher()
    event = _make_event(detected_at=datetime(2026, 7, 30, 12, 0, 0))

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        with pytest.raises(HttpPublishError):
            publisher.publish(event)
    mock_urlopen.assert_not_called()


def test_publish_converts_overlap_ratio_to_rounded_percentage():
    """명세는 DOUBLE 0.0~1.0이라고 적지만 violation_ratio 컬럼과 엔티티가 정수다 —
    실제로 저장되는 쪽에 맞춘다(백엔드 확정 시 변경 대상)."""
    publisher = _publisher()
    event = _make_event(overlap_ratio=0.375)

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["violationRatio"] == 38  # 0.375 * 100 = 37.5 -> round-half-to-even
    assert isinstance(payload["violationRatio"], int)


def test_publish_sends_human_readable_reason():
    """reason은 관리자 화면·차주 알림에 그대로 노출되는 자리라 enum 이름을 보내지 않는다."""
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(_make_event(status=ViolationStatus.DOUBLE_PARK, overlap_ratio=0.4))

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["reason"] == f"{DEFAULT_STATUS_TO_REASON['DOUBLE_PARK']} (침범 비율 40%)"
    assert "DOUBLE_PARK" not in payload["reason"]


def test_publish_reason_for_ev_overstay_uses_occupancy_not_overlap_ratio():
    """EV_OVERSTAY는 침범 비율이 아니라 점유 시간으로 판정된다(319번) — 판정에 쓰인
    시계는 dwell_seconds가 아니라 occupancy_seconds다."""
    publisher = _publisher()
    event = _make_event(
        status=ViolationStatus.EV_OVERSTAY,
        overlap_ratio=0.9,
        dwell_seconds=12.0,
        occupancy_seconds=7203.0,
    )

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(event)

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["eventType"] == "EV_OVERSTAY"
    assert payload["reason"] == f"{DEFAULT_STATUS_TO_REASON['EV_OVERSTAY']} (점유 120분)"
    assert "침범 비율" not in payload["reason"]


def test_publish_reason_omits_ratio_when_no_zone_overlap():
    """OUT_OF_ZONE은 매핑되는 구역이 없어 overlap_ratio가 항상 0.0이다 —
    "침범 비율 0%"를 붙이면 오해를 부른다."""
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(_make_event(status=ViolationStatus.OUT_OF_ZONE, overlap_ratio=0.0))

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["reason"] == DEFAULT_STATUS_TO_REASON["OUT_OF_ZONE"]


def test_publish_skips_when_session_id_cannot_be_resolved():
    """명세상 sessionId는 필수인데 RPi 입차 응답이 젯슨으로 오는 경로가 아직 없다 —
    필수 필드가 빠진 요청을 보내 400을 받는 대신 건너뛰고 경고만 남긴다."""
    publisher = _publisher(session_id_resolver=lambda _event: None)

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        publisher.publish(_make_event())

    mock_urlopen.assert_not_called()


def test_publish_skips_when_no_session_id_resolver_is_configured():
    publisher = HttpResultPublisher(base_url="http://backend.local", api_key="k", image_supplier=_images)

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        publisher.publish(_make_event())

    mock_urlopen.assert_not_called()


def test_publish_skips_when_no_images_are_available():
    """images는 명세상 1장 이상 필수인데 imageUrl을 만들 업로드 엔드포인트가 명세에 없다."""
    publisher = _publisher(image_supplier=lambda _event: [])

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        publisher.publish(_make_event())

    mock_urlopen.assert_not_called()


def test_publish_raises_when_image_supplier_omits_a_required_key():
    publisher = _publisher(image_supplier=lambda _event: [{"imageUrl": "http://x/y.jpg"}])

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        with pytest.raises(HttpPublishError):
            publisher.publish(_make_event())
    mock_urlopen.assert_not_called()


def test_publish_raises_when_status_has_no_mapping():
    publisher = _publisher(status_to_event_type={})

    with patch("http_result_publisher.urllib_request.urlopen") as mock_urlopen:
        with pytest.raises(HttpPublishError):
            publisher.publish(_make_event())
    mock_urlopen.assert_not_called()


def test_publish_treats_409_as_success():
    """409 = "동일 세션에 동일 유형의 미해결 사건이 존재함"(명세). outbox 재전송이 여기
    걸리므로 실패로 다루면 같은 사건을 영원히 재시도한다."""
    publisher = _publisher()
    error = HTTPError(url="http://backend.local/api/hw/parking-events", code=409, msg="Conflict", hdrs=None, fp=None)

    with patch("http_result_publisher.urllib_request.urlopen", side_effect=error):
        publisher.publish(_make_event())  # 예외가 새지 않아야 한다


def test_publish_raises_http_publish_error_on_http_error():
    publisher = _publisher()
    error = HTTPError(url="http://backend.local/api/hw/parking-events", code=400, msg="Bad Request", hdrs=None, fp=None)

    with patch("http_result_publisher.urllib_request.urlopen", side_effect=error):
        with pytest.raises(HttpPublishError):
            publisher.publish(_make_event())


def test_publish_raises_http_publish_error_on_connection_failure():
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", side_effect=URLError("connection refused")):
        with pytest.raises(HttpPublishError):
            publisher.publish(_make_event())


def test_publish_raises_http_publish_error_on_non_success_status_without_exception():
    """urllib은 보통 4xx/5xx에서 HTTPError를 스스로 던지지만, 그러지 않는 경우(예: 3xx
    리다이렉트가 안 따라가진 경우)를 대비한 방어 코드도 확인한다."""
    publisher = _publisher()

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response(status=305)):
        with pytest.raises(HttpPublishError):
            publisher.publish(_make_event())


def test_custom_status_to_event_type_mapping_overrides_default():
    custom_mapping = dict(DEFAULT_STATUS_TO_EVENT_TYPE)
    custom_mapping["DOUBLE_PARK"] = "CUSTOM_TYPE"
    publisher = _publisher(status_to_event_type=custom_mapping)

    with patch("http_result_publisher.urllib_request.urlopen", return_value=_mock_response()) as mock_urlopen:
        publisher.publish(_make_event(status=ViolationStatus.DOUBLE_PARK))

    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["eventType"] == "CUSTOM_TYPE"


def test_default_event_type_mapping_only_uses_values_the_backend_enum_accepts():
    """계약 문서가 요청한 AISLE_BLOCK/EV_ZONE_VIOLATION은 아직 명세·백엔드 enum에 없다 —
    없는 값을 보내면 사건 등록이 통째로 실패하므로 5종을 벗어나지 않는지 지킨다."""
    spec_event_types = {"BAD_PARKING", "DOUBLE_PARKING", "DISABLED_ZONE_VIOLATION", "EV_OVERSTAY", "OUT_OF_ZONE"}

    assert set(DEFAULT_STATUS_TO_EVENT_TYPE.values()) <= spec_event_types


def test_default_mapping_covers_every_violation_status_except_none_and_observing():
    """새 ViolationStatus가 추가됐는데 매핑을 안 넣으면 조용히 실패하는 대신, 이 테스트가
    먼저 잡아내도록 한다."""
    reportable_statuses = {
        status for status in ViolationStatus if status not in (ViolationStatus.NONE, ViolationStatus.OBSERVING)
    }
    assert set(DEFAULT_STATUS_TO_EVENT_TYPE.keys()) == {status.value for status in reportable_statuses}
    assert set(DEFAULT_STATUS_TO_REASON.keys()) == {status.value for status in reportable_statuses}

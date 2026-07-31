"""POST /internal/entry-events 라우터 회귀 테스트(T-16).

`src.main`이 아니라 라우터만 올린 최소 FastAPI 앱을 쓴다 — 전체 앱은
`zone_entry_confirm_seconds` 같은 이 라우터와 무관한 필수 설정에 묶여 있어,
여기서 검증하려는 것(payload 파싱, 인증 헤더, 멱등키, EntryEventIntake 연결)과
무관한 결합을 만든다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.entry_events_router import router
from src.application.entry_event_intake import EntryEventIntake
from src.parking.geometry import NormalizedPolygon
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.context_matcher import ContextMatcher
from src.tracking.models import BoundingBox, PhysicalVehicleId

TEST_INTERNAL_API_KEY = "test-internal-key"
VALID_HEADERS = {"Idempotency-Key": "req-1", "X-Internal-API-Key": TEST_INTERNAL_API_KEY}
ENTRY_ZONE = ParkingZone(
    zone_id=9,
    zone_number="E-01",
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=NormalizedPolygon(((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5))),
)
ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)


@pytest.fixture(autouse=True)
def _internal_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_API_KEY)
    from src.config.settings import get_settings

    get_settings.cache_clear()


def make_client() -> tuple[TestClient, ContextMatcher]:
    app = FastAPI()
    app.include_router(router)
    matcher = ContextMatcher(zones=ZoneRegistry([ENTRY_ZONE]))
    app.state.entry_event_intake = EntryEventIntake(matcher)
    return TestClient(app), matcher


def make_payload(**overrides) -> dict:
    payload = {
        "trackingId": "gate-uuid-1",
        "recognizedPlateNumber": "12가3456",
        "entryTime": "2026-07-31T12:00:00+00:00",
        "accessDecision": "ALLOW",
        "registered": True,
        "vehicleId": 10,
        "isDisabledVehicle": False,
        "isElectric": True,
        "vehicleStatus": "ACTIVE",
        "sessionId": 55,
        "duplicateRequest": False,
    }
    payload.update(overrides)
    return payload


class TestReceiveEntryEvent:
    def test_accepts_valid_payload_and_queues_it_on_the_matcher(self):
        client, matcher = make_client()

        response = client.post("/internal/entry-events", json=make_payload(), headers=VALID_HEADERS)

        assert response.status_code == 202
        assert response.json() == {"accepted": True}
        # 대기열에 실제로 쌓였는지: ENTRY_EXIT 매칭을 흉내 내 확인한다.
        context = matcher.match(
            physical_vehicle_id=PhysicalVehicleId("veh-1"),
            bbox=ENTRY_BBOX,
            now=datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert context is not None
        assert context.vehicle_id == 10

    def test_duplicate_idempotency_key_is_not_re_queued(self):
        client, _matcher = make_client()

        first = client.post("/internal/entry-events", json=make_payload(), headers=VALID_HEADERS)
        second = client.post("/internal/entry-events", json=make_payload(), headers=VALID_HEADERS)

        assert first.json() == {"accepted": True}
        assert second.json() == {"accepted": False}

    def test_deny_payload_with_null_vehicle_fields_is_still_accepted(self):
        """미등록 차량(DENY)도 여전히 카메라에 잡히는 실제 차량이라 큐에 실어야 한다."""

        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(
                accessDecision="DENY", registered=False, vehicleId=None,
                isDisabledVehicle=None, isElectric=None, vehicleStatus=None, sessionId=None,
            ),
            headers=VALID_HEADERS,
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": True}

    def test_missing_idempotency_key_header_is_rejected(self):
        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(),
            headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
        )

        assert response.status_code == 422

    def test_naive_entry_time_is_rejected(self):
        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(entryTime="2026-07-31T12:00:00"),
            headers=VALID_HEADERS,
        )

        assert response.status_code == 422

    def test_missing_internal_api_key_header_is_rejected(self):
        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(),
            headers={"Idempotency-Key": "req-1"},
        )

        assert response.status_code == 422

    def test_wrong_internal_api_key_is_unauthorized(self):
        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(),
            headers={"Idempotency-Key": "req-1", "X-Internal-API-Key": "wrong-key"},
        )

        assert response.status_code == 401

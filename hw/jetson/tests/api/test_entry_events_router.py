"""POST /internal/entry-events 라우터 회귀 테스트(T-16).

`src.main`이 아니라 라우터만 올린 최소 FastAPI 앱을 쓴다 — 전체 앱은
`zone_entry_confirm_seconds` 같은 이 라우터와 무관한 필수 설정에 묶여 있어,
여기서 검증하려는 것(payload 파싱, 멱등키, ContextMatcher 연결)과 무관한
결합을 만든다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.entry_events_router import router
from src.tracking.context_matcher import ContextMatcher


def make_client() -> tuple[TestClient, ContextMatcher]:
    app = FastAPI()
    app.include_router(router)
    matcher = ContextMatcher()
    app.state.context_matcher = matcher
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

        response = client.post(
            "/internal/entry-events",
            json=make_payload(),
            headers={"Idempotency-Key": "req-1"},
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": True}
        # 대기열에 실제로 쌓였는지: ENTRY_EXIT 매칭을 흉내 내 확인한다.
        from datetime import datetime, timezone

        from src.tracking.models import PhysicalVehicleId

        context = matcher.match(
            physical_vehicle_id=PhysicalVehicleId("veh-1"),
            in_entry_zone=True,
            now=datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert context is not None
        assert context.vehicle_id == 10

    def test_duplicate_idempotency_key_is_not_re_queued(self):
        client, _matcher = make_client()
        headers = {"Idempotency-Key": "req-1"}

        first = client.post("/internal/entry-events", json=make_payload(), headers=headers)
        second = client.post("/internal/entry-events", json=make_payload(), headers=headers)

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
            headers={"Idempotency-Key": "req-2"},
        )

        assert response.status_code == 202
        assert response.json() == {"accepted": True}

    def test_missing_idempotency_key_header_is_rejected(self):
        client, _matcher = make_client()

        response = client.post("/internal/entry-events", json=make_payload())

        assert response.status_code == 422

    def test_naive_entry_time_is_rejected(self):
        client, _matcher = make_client()

        response = client.post(
            "/internal/entry-events",
            json=make_payload(entryTime="2026-07-31T12:00:00"),
            headers={"Idempotency-Key": "req-3"},
        )

        assert response.status_code == 422

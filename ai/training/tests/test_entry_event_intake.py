from datetime import datetime, timedelta, timezone

import pytest
from entry_event_intake import EntryEventIntake, EntryEventIntakeError, IncomingEntryEvent
from jetson_vehicle_tracking_baseline import (
    BoundingBox,
    NormalizedPolygon,
    ParkingZone,
    ViolationMonitor,
    VehicleBox,
    ZoneRegistry,
    ZoneType,
)


# 박신영(HW) MR 리뷰에서 공유한 실제 payload 예시.
SAMPLE_PAYLOAD = {
    "trackingId": "d290f1ee-6c54-4b01-90e6-d701748f0851",
    "recognizedPlateNumber": "12가3456",
    "entryTime": "2026-07-31T12:34:56+09:00",
    "accessDecision": "ALLOW",
    "registered": True,
    "vehicleId": 10,
    "isDisabledVehicle": False,
    "isElectric": True,
    "vehicleStatus": "ACTIVE",
    "sessionId": 55,
    "duplicateRequest": False,
}


def _make_monitor() -> ViolationMonitor:
    entry_zone = ParkingZone(
        zone_id=1,
        zone_number="ENTRY-01",
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=NormalizedPolygon(((0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3))),
    )
    return ViolationMonitor(ZoneRegistry([entry_zone]), min_overlap_ratio=0.40, entry_match_window_seconds=10.0)


class TestIncomingEntryEventFromPayload:
    def test_parses_full_payload(self):
        incoming = IncomingEntryEvent.from_payload(SAMPLE_PAYLOAD)
        assert incoming.tracking_id == "d290f1ee-6c54-4b01-90e6-d701748f0851"
        assert incoming.recognized_plate_number == "12가3456"
        assert incoming.access_decision == "ALLOW"
        assert incoming.registered is True
        assert incoming.vehicle_id == 10
        assert incoming.is_disabled_vehicle is False
        assert incoming.is_electric is True
        assert incoming.vehicle_status == "ACTIVE"
        assert incoming.session_id == 55
        assert incoming.duplicate_request is False

    def test_parses_deny_payload_with_null_vehicle_fields(self):
        payload = {
            **SAMPLE_PAYLOAD,
            "accessDecision": "DENY",
            "registered": False,
            "vehicleId": None,
            "isDisabledVehicle": None,
            "isElectric": None,
            "vehicleStatus": None,
            "sessionId": None,
        }
        incoming = IncomingEntryEvent.from_payload(payload)
        assert incoming.access_decision == "DENY"
        assert incoming.vehicle_id is None

    def test_raises_on_missing_required_field(self):
        payload = dict(SAMPLE_PAYLOAD)
        del payload["trackingId"]
        with pytest.raises(EntryEventIntakeError):
            IncomingEntryEvent.from_payload(payload)

    def test_raises_on_naive_entry_time(self):
        payload = {**SAMPLE_PAYLOAD, "entryTime": "2026-07-31T12:34:56"}
        with pytest.raises(EntryEventIntakeError):
            IncomingEntryEvent.from_payload(payload)

    def test_to_entry_event_carries_gate_tracking_id(self):
        incoming = IncomingEntryEvent.from_payload(SAMPLE_PAYLOAD)
        event = incoming.to_entry_event()
        assert event.plate_number == "12가3456"
        assert event.gate_tracking_id == "d290f1ee-6c54-4b01-90e6-d701748f0851"

    def test_to_entry_event_converts_deny_too(self):
        """DENY(미등록)여도 EntryEvent로 변환된다 — 미등록 차량도 위반 판정 대상이다."""
        payload = {**SAMPLE_PAYLOAD, "accessDecision": "DENY", "registered": False, "vehicleId": None}
        incoming = IncomingEntryEvent.from_payload(payload)
        event = incoming.to_entry_event()
        assert event.plate_number == "12가3456"


class TestEntryEventIntakeHandle:
    def test_handle_adds_entry_event_and_matches_track(self):
        monitor = _make_monitor()
        intake = EntryEventIntake(monitor)
        base_time = datetime(2026, 7, 31, 12, 34, 56, tzinfo=timezone.utc)
        payload = {**SAMPLE_PAYLOAD, "entryTime": base_time.isoformat()}

        processed = intake.handle(payload, idempotency_key="key-1")
        assert processed is True

        monitor.update(
            [
                VehicleBox(
                    track_id=1,
                    bbox=BoundingBox(0.05, 0.05, 0.25, 0.25),
                    confidence=0.9,
                    frame_id=1,
                    captured_at=base_time + timedelta(seconds=2),
                )
            ]
        )
        assert monitor._tracks[1].plate_number == "12가3456"
        assert monitor._tracks[1].gate_tracking_id == "d290f1ee-6c54-4b01-90e6-d701748f0851"

    def test_handle_ignores_duplicate_idempotency_key(self):
        """같은 멱등키로 재전송하면 두 번째 호출은 무시한다(네트워크 재시도 대비)."""
        monitor = _make_monitor()
        intake = EntryEventIntake(monitor)
        base_time = datetime(2026, 7, 31, 12, 34, 56, tzinfo=timezone.utc)
        payload = {**SAMPLE_PAYLOAD, "entryTime": base_time.isoformat()}

        first = intake.handle(payload, idempotency_key="same-key")
        second = intake.handle(payload, idempotency_key="same-key")

        assert first is True
        assert second is False
        assert len(monitor._pending_entry_events) == 1  # 두 번 쌓이지 않음

    def test_handle_processes_different_idempotency_keys_independently(self):
        monitor = _make_monitor()
        intake = EntryEventIntake(monitor)
        base_time = datetime(2026, 7, 31, 12, 34, 56, tzinfo=timezone.utc)
        payload_a = {**SAMPLE_PAYLOAD, "entryTime": base_time.isoformat(), "trackingId": "aaaa"}
        payload_b = {**SAMPLE_PAYLOAD, "entryTime": base_time.isoformat(), "trackingId": "bbbb"}

        assert intake.handle(payload_a, idempotency_key="key-a") is True
        assert intake.handle(payload_b, idempotency_key="key-b") is True
        assert len(monitor._pending_entry_events) == 2

    def test_handle_raises_on_malformed_payload_regardless_of_key(self):
        monitor = _make_monitor()
        intake = EntryEventIntake(monitor)
        with pytest.raises(EntryEventIntakeError):
            intake.handle({"trackingId": "x"}, idempotency_key="key-1")


class TestEntryEventIntakeMemoryBound:
    def test_forgets_oldest_key_once_capacity_exceeded(self):
        """무제한으로 키를 기억하면 장시간 운영 시 메모리가 계속 늘어난다 —
        가장 오래된 키부터 버려서 상한을 지킨다."""
        monitor = _make_monitor()
        intake = EntryEventIntake(monitor, max_remembered_keys=2)
        base_time = datetime(2026, 7, 31, 12, 34, 56, tzinfo=timezone.utc)

        def payload(tracking_id: str) -> dict:
            return {**SAMPLE_PAYLOAD, "entryTime": base_time.isoformat(), "trackingId": tracking_id}

        intake.handle(payload("t1"), idempotency_key="key-1")
        intake.handle(payload("t2"), idempotency_key="key-2")
        intake.handle(payload("t3"), idempotency_key="key-3")  # key-1이 밀려남

        # key-1은 더 이상 기억하지 못하므로 재전송이 "새로 처리됨"으로 취급된다.
        assert intake.handle(payload("t1-retry"), idempotency_key="key-1") is True
        # key-3은 아직 기억하고 있으므로 재전송은 무시된다.
        assert intake.handle(payload("t3-retry"), idempotency_key="key-3") is False

    def test_rejects_non_positive_max_remembered_keys(self):
        monitor = _make_monitor()
        with pytest.raises(ValueError):
            EntryEventIntake(monitor, max_remembered_keys=0)

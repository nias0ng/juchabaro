"""ContextMatcher 회귀 테스트(T-16)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from src.communication.models import EntryContext
from src.parking.geometry import NormalizedPolygon
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.context_matcher import ContextMatcher
from src.tracking.models import BoundingBox, ParkingSessionId, PhysicalVehicleId, VehicleId

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
ENTRY_ZONE = ParkingZone(
    zone_id=9,
    zone_number="E-01",
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=NormalizedPolygon(((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5))),
)
ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)  # ENTRY_ZONE 안에 거의 전부 겹침
FAR_BBOX = BoundingBox(0.8, 0.8, 0.9, 0.9)  # 어떤 구역과도 안 겹침


def make_matcher(**overrides) -> ContextMatcher:
    kwargs = {"zones": ZoneRegistry([ENTRY_ZONE])}
    kwargs.update(overrides)
    return ContextMatcher(**kwargs)


def make_entry_context(*, entry_time: datetime = NOW, session_id: int | None = 55) -> EntryContext:
    return EntryContext(
        tracking_id="gate-uuid-1",
        recognized_plate_number="12가3456",
        entry_time=entry_time,
        access_decision="ALLOW",
        registered=True,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
        vehicle_status="ACTIVE",
        session_id=session_id,
        duplicate_request=False,
    )


class TestMatch:
    def test_returns_none_when_no_pending_entry_context(self):
        matcher = make_matcher()

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        assert result is None

    def test_matches_pending_entry_context_when_bbox_overlaps_entry_zone(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        assert result is not None
        assert result.vehicle_id == VehicleId(10)
        assert result.parking_session_id == ParkingSessionId(55)
        assert result.is_electric is True
        assert result.is_disabled_vehicle is False

    def test_does_not_match_when_bbox_far_from_entry_zone(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=FAR_BBOX, now=NOW)

        assert result is None

    def test_no_entry_exit_zone_in_registry_never_matches(self):
        disabled_zone = ParkingZone(
            zone_id=1, zone_number="D-01", zone_type=ZoneType.DISABLED,
            polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
        )
        matcher = make_matcher(zones=ZoneRegistry([disabled_zone]))
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        assert result is None

    def test_future_dated_entry_context_is_not_eligible_yet(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(entry_time=NOW + timedelta(seconds=5)), idempotency_key="key-1")

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        assert result is None

    def test_picks_earliest_entry_time_not_insertion_order(self):
        """비동기 처리로 삽입 순서가 실제 촬영 순서와 어긋나도 시간순으로 매칭돼야 한다."""

        matcher = make_matcher()
        later = make_entry_context(entry_time=NOW, session_id=1)
        earlier = make_entry_context(entry_time=NOW - timedelta(seconds=3), session_id=2)
        matcher.add_entry_context(later, idempotency_key="key-later")
        matcher.add_entry_context(earlier, idempotency_key="key-earlier")

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        assert result is not None
        assert result.parking_session_id == ParkingSessionId(2)

    def test_matched_entry_context_is_removed_from_pending_queue(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-2"), bbox=ENTRY_BBOX, now=NOW)

        assert result is None

    def test_already_matched_vehicle_returns_cached_context_without_zone_check(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        first = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        second = matcher.match(
            physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=FAR_BBOX, now=NOW + timedelta(seconds=1)
        )

        assert second is first


class TestPruneExpired:
    def test_prunes_entry_context_older_than_window(self):
        matcher = make_matcher(entry_match_window_seconds=10.0)
        matcher.add_entry_context(make_entry_context(entry_time=NOW - timedelta(seconds=11)), idempotency_key="key-1")

        matcher.prune_expired(NOW)

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)
        assert result is None

    def test_keeps_entry_context_within_window(self):
        matcher = make_matcher(entry_match_window_seconds=10.0)
        matcher.add_entry_context(make_entry_context(entry_time=NOW - timedelta(seconds=9)), idempotency_key="key-1")

        matcher.prune_expired(NOW)

        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)
        assert result is not None


class TestIdempotency:
    def test_duplicate_idempotency_key_is_ignored(self):
        matcher = make_matcher()

        first = matcher.add_entry_context(make_entry_context(), idempotency_key="dup-key")
        second = matcher.add_entry_context(make_entry_context(), idempotency_key="dup-key")

        assert first is True
        assert second is False
        # 중복 추가가 무시됐으므로 대기열에는 하나만 있어야 한다.
        matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)
        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-2"), bbox=ENTRY_BBOX, now=NOW)
        assert result is None

    def test_rejects_non_positive_max_remembered_keys(self):
        with pytest.raises(ValueError):
            make_matcher(max_remembered_idempotency_keys=0)

    def test_forgets_oldest_idempotency_key_beyond_bound(self):
        matcher = make_matcher(max_remembered_idempotency_keys=1)
        matcher.add_entry_context(make_entry_context(session_id=1), idempotency_key="key-1")
        matcher.add_entry_context(make_entry_context(session_id=2), idempotency_key="key-2")

        # key-1은 경계를 넘어가며 잊혔으니 재전송으로 취급되지 않고 다시 추가된다.
        reaccepted = matcher.add_entry_context(make_entry_context(session_id=3), idempotency_key="key-1")

        assert reaccepted is True


class TestForget:
    def test_forget_clears_cached_match(self):
        matcher = make_matcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)

        matcher.forget(PhysicalVehicleId("veh-1"))

        # 캐시가 지워졌고 대기열도 비었으니 다시 물어봐도 매칭되지 않는다.
        result = matcher.match(physical_vehicle_id=PhysicalVehicleId("veh-1"), bbox=ENTRY_BBOX, now=NOW)
        assert result is None

    def test_forget_unknown_vehicle_is_a_no_op(self):
        matcher = make_matcher()

        matcher.forget(PhysicalVehicleId("never-matched"))


class TestConcurrency:
    def test_concurrent_add_with_same_idempotency_key_accepts_exactly_once(self):
        """여러 라즈베리파이 요청이 같은 Idempotency-Key로 동시에 도착해도
        정확히 한 번만 대기열에 실려야 한다(AI 리뷰 제안 반영)."""

        import threading

        matcher = make_matcher()
        results: list[bool] = []
        results_lock = threading.Lock()
        start = threading.Barrier(20)

        def _add() -> None:
            start.wait()
            accepted = matcher.add_entry_context(make_entry_context(), idempotency_key="same-key")
            with results_lock:
                results.append(accepted)

        threads = [threading.Thread(target=_add) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results.count(True) == 1
        assert results.count(False) == 19

"""EntryContextEnricher 회귀 테스트(T-16)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.application.context_enrichment import EntryContextEnricher
from src.communication.models import EntryContext
from src.parking.geometry import NormalizedPolygon
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.context_matcher import ContextMatcher
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleSnapshot,
    TrackingBatch,
    TrackSegmentId,
    VehicleContext,
)

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
ENTRY_ZONE = ParkingZone(
    zone_id=9,
    zone_number="E-01",
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=NormalizedPolygon(((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5))),
)
ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)  # ENTRY_ZONE 안에 거의 전부 겹침
FAR_BBOX = BoundingBox(0.8, 0.8, 0.9, 0.9)  # 어떤 구역과도 안 겹침


def make_entry_context() -> EntryContext:
    return EntryContext(
        tracking_id="gate-uuid-1",
        recognized_plate_number="12가3456",
        entry_time=NOW,
        access_decision="ALLOW",
        registered=True,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
        vehicle_status="ACTIVE",
        session_id=55,
        duplicate_request=False,
    )


def make_snapshot(*, physical_vehicle_id: str = "veh-1", bbox: BoundingBox, context=None) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=physical_vehicle_id,
        track_segment_id=TrackSegmentId(1),
        bbox=bbox,
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=NOW,
        camera_id="cam-1",
        context=context,
    )


def make_batch(vehicles, *, ended_vehicle_ids=()) -> TrackingBatch:
    return TrackingBatch(
        camera_id="cam-1",
        frame_id=1,
        observed_at=NOW,
        vehicles=tuple(vehicles),
        ended_vehicle_ids=tuple(ended_vehicle_ids),
        source_available=True,
    )


class TestEnrich:
    def test_fills_context_for_vehicle_overlapping_entry_zone(self):
        matcher = ContextMatcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([ENTRY_ZONE]), matcher=matcher)
        batch = make_batch([make_snapshot(bbox=ENTRY_BBOX)])

        result = enricher.enrich(batch)

        assert result.vehicles[0].context is not None
        assert result.vehicles[0].context.vehicle_id == 10

    def test_does_not_fill_context_when_far_from_entry_zone(self):
        matcher = ContextMatcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([ENTRY_ZONE]), matcher=matcher)
        batch = make_batch([make_snapshot(bbox=FAR_BBOX)])

        result = enricher.enrich(batch)

        assert result.vehicles[0].context is None

    def test_does_not_overwrite_existing_context(self):
        """이미 context가 있는 차량은 재매칭하지 않는다 — 대기열의 다른 이벤트가
        엉뚱하게 덮어쓰면 안 된다."""

        existing = VehicleContext(parking_session_id=1, vehicle_id=1, is_electric=None, is_disabled_vehicle=None)
        matcher = ContextMatcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([ENTRY_ZONE]), matcher=matcher)
        batch = make_batch([make_snapshot(bbox=ENTRY_BBOX, context=existing)])

        result = enricher.enrich(batch)

        assert result.vehicles[0].context is existing

    def test_no_entry_exit_zone_in_registry_is_a_no_op(self):
        disabled_zone = ParkingZone(
            zone_id=1, zone_number="D-01", zone_type=ZoneType.DISABLED,
            polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
        )
        matcher = ContextMatcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([disabled_zone]), matcher=matcher)
        batch = make_batch([make_snapshot(bbox=ENTRY_BBOX)])

        result = enricher.enrich(batch)

        assert result is batch

    def test_forgets_matched_cache_for_ended_vehicles(self):
        matcher = ContextMatcher()
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([ENTRY_ZONE]), matcher=matcher)
        first_batch = make_batch([make_snapshot(bbox=ENTRY_BBOX)])
        enricher.enrich(first_batch)  # veh-1이 매칭돼 캐시에 들어간다

        second_batch = make_batch([], ended_vehicle_ids=("veh-1",))
        enricher.enrich(second_batch)

        # 캐시가 지워졌으니 veh-1이 다시 나타나도(대기열은 비어 있음) 매칭되지 않는다.
        third_batch = make_batch([make_snapshot(bbox=ENTRY_BBOX)])
        result = enricher.enrich(third_batch)
        assert result.vehicles[0].context is None

    def test_prunes_expired_entry_context_using_batch_observed_at(self):
        matcher = ContextMatcher(entry_match_window_seconds=1.0)
        matcher.add_entry_context(make_entry_context(), idempotency_key="key-1")
        enricher = EntryContextEnricher(zones=ZoneRegistry([ENTRY_ZONE]), matcher=matcher)

        late_batch = TrackingBatch(
            camera_id="cam-1", frame_id=1, observed_at=NOW + timedelta(seconds=5),
            vehicles=(make_snapshot(bbox=ENTRY_BBOX),), ended_vehicle_ids=(), source_available=True,
        )

        result = enricher.enrich(late_batch)

        assert result.vehicles[0].context is None

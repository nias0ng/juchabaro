"""ParkingPipeline 통합 회귀 테스트 (440, 관통 1단계).

test_zone_visit_incident_flow.py가 검증한 ZoneVisitTracker→restricted_zone→
IncidentReducer 연결 계약을, 실제 TrackingBatch를 입력으로 받는 조립기
관점에서 다시 검증한다.
"""

from datetime import datetime, timedelta, timezone

from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import IncidentState, IncidentTransitionType
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    TrackingBatch,
    VehicleContext,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)  # 구역(0.1~0.3) 안에 완전히 들어감
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)  # 구역 밖
DISABLED_ZONE = ParkingZone(
    zone_id=1,
    zone_number="D-01",
    zone_type=ZoneType.DISABLED,
    polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
)
GENERAL_ZONE = ParkingZone(
    zone_id=2,
    zone_number="G-01",
    zone_type=ZoneType.GENERAL,
    polygon=NormalizedPolygon(((0.5, 0.5), (0.9, 0.5), (0.9, 0.9), (0.5, 0.9))),
)
UNAUTHORIZED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=False
)


def make_pipeline(*, zones=(DISABLED_ZONE,), entry=1.0, exit_=1.0, stale=300.0, min_overlap=0.5) -> ParkingPipeline:
    return ParkingPipeline(
        zones=ZoneRegistry(list(zones)),
        zone_visit_tracker=InMemoryZoneVisitTracker(
            entry_confirm_seconds=entry, exit_confirm_seconds=exit_, stale_after_seconds=stale
        ),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=min_overlap,
    )


def snapshot(
    *, bbox=INSIDE_BBOX, at: datetime = T0, context=UNAUTHORIZED, motion=MotionSignal.STATIONARY
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=bbox,
        confidence=0.9,
        motion_signal=motion,
        observed_at=at,
        camera_id="cam-1",
        context=context,
    )


def batch(*vehicles: PhysicalVehicleSnapshot, at: datetime, frame_id: int = 1, ended=()) -> TrackingBatch:
    return TrackingBatch(
        camera_id="cam-1",
        frame_id=frame_id,
        observed_at=at,
        vehicles=tuple(vehicles),
        ended_vehicle_ids=tuple(ended),
        source_available=True,
    )


def test_unauthorized_vehicle_entering_disabled_zone_opens_then_resolves():
    pipeline = make_pipeline()

    r0 = pipeline.process(batch(snapshot(at=T0), at=T0))
    assert r0.incident_transitions == ()  # ENTERING — 아직 확정 전

    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert [t.transition_type for t in r1.incident_transitions] == [IncidentTransitionType.OPEN]

    r2 = pipeline.process(
        batch(snapshot(bbox=OUTSIDE_BBOX, at=T0 + timedelta(seconds=2)), at=T0 + timedelta(seconds=2))
    )
    assert r2.incident_transitions == ()  # EXITING — 아직 안 닫힘

    r3 = pipeline.process(
        batch(snapshot(bbox=OUTSIDE_BBOX, at=T0 + timedelta(seconds=3)), at=T0 + timedelta(seconds=3))
    )
    assert [t.transition_type for t in r3.incident_transitions] == [IncidentTransitionType.RESOLVE]
    assert r3.incident_transitions[0].incident.incident_id == r1.incident_transitions[0].incident.incident_id


def test_qualified_vehicle_never_opens_incident():
    pipeline = make_pipeline()
    qualified = VehicleContext(parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=True)

    r0 = pipeline.process(batch(snapshot(at=T0, context=qualified), at=T0))
    r1 = pipeline.process(
        batch(snapshot(at=T0 + timedelta(seconds=1), context=qualified), at=T0 + timedelta(seconds=1))
    )

    assert r0.incident_transitions == ()
    assert r1.incident_transitions == ()


def test_vehicle_in_general_zone_produces_no_restricted_zone_incident():
    """GENERAL 구역은 restricted_zone 규칙 대상이 아니다 — 방문은 생기지만 사건은 없다."""
    pipeline = make_pipeline(zones=(GENERAL_ZONE,))

    pipeline.process(batch(snapshot(bbox=BoundingBox(0.55, 0.55, 0.65, 0.65), at=T0), at=T0))
    r1 = pipeline.process(
        batch(
            snapshot(bbox=BoundingBox(0.55, 0.55, 0.65, 0.65), at=T0 + timedelta(seconds=1)),
            at=T0 + timedelta(seconds=1),
        )
    )

    assert r1.incident_transitions == ()
    assert len(r1.zone_visit_updates) == 1  # 방문 자체는 여전히 추적된다


def test_lost_track_is_resolved_via_prune_using_last_known_snapshot():
    """추적이 끊긴 차량(다음 배치에 없음)도 유휴 한도를 넘기면 사건이 닫혀야 한다.

    이 프레임의 TrackingBatch에는 그 차량이 없으므로, 마지막으로 캐싱해 둔
    스냅샷으로 RuleContext.vehicle을 채울 수 있는지가 핵심이다.
    """
    pipeline = make_pipeline(stale=5.0)
    pipeline.process(batch(snapshot(at=T0), at=T0))
    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert [t.transition_type for t in r1.incident_transitions] == [IncidentTransitionType.OPEN]

    # 차량이 다음 배치부터 아예 안 보인다 — 관측이 뚝 끊김.
    empty_at = T0 + timedelta(seconds=10)
    r2 = pipeline.process(batch(at=empty_at))

    assert [t.transition_type for t in r2.incident_transitions] == [IncidentTransitionType.RESOLVE]


def test_incident_reducer_state_matches_expected_lifecycle():
    pipeline = make_pipeline()
    reducer = pipeline._incident_reducer  # 스냅샷 조회용 — 화이트박스 확인

    pipeline.process(batch(snapshot(at=T0), at=T0))
    pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))

    states = [incident.state for incident in reducer.snapshot()]
    assert states == [IncidentState.EDGE_CONFIRMED]


def test_ended_vehicle_that_never_visited_a_zone_is_dropped_from_snapshot_cache():
    """구역을 한 번도 안 밟은 채 사라진 차량은 prune()이 절대 돌려주지 않는다
    (방문 자체가 생긴 적이 없어서) — ended_vehicle_ids로 직접 정리하지 않으면
    이 캐시가 지나가기만 하는 차량마다 무한히 커진다."""
    pipeline = make_pipeline()
    passerby = snapshot(bbox=OUTSIDE_BBOX, at=T0)  # 구역 밖만 지나감, 방문 없음

    pipeline.process(batch(passerby, at=T0))
    assert CAR in pipeline._last_snapshot

    pipeline.process(batch(at=T0 + timedelta(seconds=1), ended=(CAR,)))

    assert CAR not in pipeline._last_snapshot

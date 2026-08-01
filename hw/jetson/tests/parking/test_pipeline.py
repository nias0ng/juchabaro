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
EV_ZONE = ParkingZone(
    zone_id=3,
    zone_number="EV-01",
    zone_type=ZoneType.EV_FAST,
    # DISABLED_ZONE과 같은 자리에 겹쳐 둔다 — 한 차량이 두 전용구역에
    # 동시에 INSIDE인 상황을 만들기 위해서다(446 AI 리뷰 제안 시나리오).
    polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
    allowed_minutes=60.0,
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


def test_lost_track_is_resolved_via_prune_without_needing_a_snapshot():
    """추적이 끊긴 차량(다음 배치에 없음)도 유휴 한도를 넘기면 사건이 닫혀야 한다.

    `resolve_scope`는 스냅샷도 규칙도 없이 `zone_visit_id`만으로 해소하므로
    (446 후속 리뷰), 이 프레임의 TrackingBatch에 그 차량이 전혀 없어도
    (캐싱된 스냅샷이 없어도) RESOLVE가 나가야 한다.
    """
    pipeline = make_pipeline(stale=5.0)
    pipeline.process(batch(snapshot(at=T0), at=T0))
    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert [t.transition_type for t in r1.incident_transitions] == [IncidentTransitionType.OPEN]

    # 차량이 다음 배치부터 아예 안 보인다 — 관측이 뚝 끊김.
    empty_at = T0 + timedelta(seconds=10)
    r2 = pipeline.process(batch(at=empty_at))

    assert [t.transition_type for t in r2.incident_transitions] == [IncidentTransitionType.RESOLVE]


def test_ended_vehicle_ids_reported_before_prune_does_not_drop_the_resolve():
    """실제 조립기가 하는 순서 그대로: 차량이 INSIDE인 채로 추적이 끊기면
    tracking 계층은 그 즉시(같은 프레임) ended_vehicle_ids로 종료를 보고한다
    — 몇 분 뒤 prune()이 강제 종료를 반환할 때까지 기다리지 않는다.

    446 이전에는 이 조합에서 버그가 났다: ended_vehicle_ids 처리가 스냅샷
    캐시를 그 프레임에서 바로 비웠고, 그 뒤 prune()이 방문을 강제 종료로
    반환해도 캐시가 비어 있어 판정이 생략돼 사건이 영원히 안 닫혔다(리뷰
    지적). 기존 `test_lost_track_is_resolved_via_prune_without_needing_a_snapshot`는
    ended_vehicle_ids를 비워둔 채로만 테스트해서 이 조합을 검증하지 못했다.
    """
    pipeline = make_pipeline(stale=5.0)
    pipeline.process(batch(snapshot(at=T0), at=T0))
    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert [t.transition_type for t in r1.incident_transitions] == [IncidentTransitionType.OPEN]

    # 차량이 INSIDE인 채로 이번 프레임에 tracking이 종료를 보고한다.
    r2 = pipeline.process(batch(at=T0 + timedelta(seconds=2), ended=(CAR,)))
    assert r2.incident_transitions == ()  # 아직 stale 시간이 안 지남

    # 유휴 한도(stale)를 넘긴 뒤에야 prune()이 강제 종료를 반환한다.
    r3 = pipeline.process(batch(at=T0 + timedelta(seconds=10)))
    assert [t.transition_type for t in r3.incident_transitions] == [IncidentTransitionType.RESOLVE]
    assert r3.incident_transitions[0].incident.incident_id == r1.incident_transitions[0].incident.incident_id


def test_multiple_simultaneous_visits_all_resolve_after_track_loss():
    """차량 한 대가 두 전용구역(장애인+EV)에 동시에 INSIDE인 채로 추적이
    끊기면, prune()이 두 방문을 모두 강제 종료로 반환하고 둘 다 빠짐없이
    RESOLVE돼야 한다(446 AI 리뷰 제안) — 여러 방문을 순회하며 각각
    resolve_scope로 해소하는 경로를 pipeline 레벨에서 확인한다."""
    pipeline = make_pipeline(zones=(DISABLED_ZONE, EV_ZONE), stale=5.0)
    pipeline.process(batch(snapshot(at=T0), at=T0))
    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert len(r1.incident_transitions) == 2
    assert all(t.transition_type is IncidentTransitionType.OPEN for t in r1.incident_transitions)
    assert {t.incident.key.rule_code for t in r1.incident_transitions} == {
        "DISABLED_ZONE_UNAUTHORIZED", "EV_ZONE_UNAUTHORIZED"
    }

    # 차량이 두 구역에 동시에 INSIDE인 채로 이번 프레임에 추적이 끊긴다.
    pipeline.process(batch(at=T0 + timedelta(seconds=2), ended=(CAR,)))

    # 유휴 한도를 넘긴 뒤에야 prune()이 두 방문을 모두 강제 종료로 반환한다.
    r3 = pipeline.process(batch(at=T0 + timedelta(seconds=10)))
    assert len(r3.incident_transitions) == 2
    assert all(t.transition_type is IncidentTransitionType.RESOLVE for t in r3.incident_transitions)
    assert {t.incident.key.rule_code for t in r3.incident_transitions} == {
        "DISABLED_ZONE_UNAUTHORIZED", "EV_ZONE_UNAUTHORIZED"
    }


def test_resolves_even_if_the_zone_definition_is_deleted_before_resolution():
    """신영 님 리뷰 시나리오: 방문이 닫히는 시점에 그 구역이 `ZoneRegistry`에서
    이미 사라졌어도(서버 구역 동기화 등) RESOLVE는 나가야 한다 — 해소는
    `zone_visit_id`만으로 처리되고 규칙(구역 재조회)을 거치지 않으므로,
    구역이 없어져도 rule_code를 재구성할 필요 자체가 없다."""
    pipeline = make_pipeline(stale=5.0)
    pipeline.process(batch(snapshot(at=T0), at=T0))
    r1 = pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))
    assert [t.transition_type for t in r1.incident_transitions] == [IncidentTransitionType.OPEN]

    # 서버 구역 동기화로 이 구역이 사라졌다고 가정한다(화이트박스 교체).
    pipeline._zones = ZoneRegistry([])

    # 차량이 INSIDE인 채로 추적이 끊기고, 유휴 한도를 넘겨 prune()이 강제 종료한다.
    pipeline.process(batch(at=T0 + timedelta(seconds=2), ended=(CAR,)))
    r3 = pipeline.process(batch(at=T0 + timedelta(seconds=10)))

    assert [t.transition_type for t in r3.incident_transitions] == [IncidentTransitionType.RESOLVE]
    assert r3.incident_transitions[0].incident.incident_id == r1.incident_transitions[0].incident.incident_id


def test_incident_reducer_state_matches_expected_lifecycle():
    pipeline = make_pipeline()
    reducer = pipeline._incident_reducer  # 스냅샷 조회용 — 화이트박스 확인

    pipeline.process(batch(snapshot(at=T0), at=T0))
    pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1)), at=T0 + timedelta(seconds=1)))

    states = [incident.state for incident in reducer.snapshot()]
    assert states == [IncidentState.EDGE_CONFIRMED]


def test_ev_overstay_opens_after_allowed_minutes_then_resolves_on_exit():
    """T-11/450: EV구역 점유가 allowed_minutes(60분)를 넘기면 OPEN, 이탈하면
    RESOLVE — restricted_zone과 나란히 배선된 ev_overstay 규칙을 pipeline
    레벨에서 확인한다. 전기차로 자격을 갖춘 차량이라 EV_ZONE_UNAUTHORIZED는
    성립하지 않고, EV_OVERSTAY만 점유 시간으로 판단된다."""
    pipeline = make_pipeline(zones=(EV_ZONE,))
    electric = VehicleContext(parking_session_id=1, vehicle_id=1, is_electric=True, is_disabled_vehicle=False)

    r0 = pipeline.process(batch(snapshot(at=T0, context=electric), at=T0))
    assert r0.incident_transitions == ()  # ENTERING — 아직 확정 전

    entered_at = T0 + timedelta(seconds=1)
    r1 = pipeline.process(batch(snapshot(at=entered_at, context=electric), at=entered_at))
    assert r1.incident_transitions == ()  # INSIDE 확정만 됨 — 점유 시간이 아직 60분 미만

    still_under_limit = T0 + timedelta(minutes=59)
    r2 = pipeline.process(batch(snapshot(at=still_under_limit, context=electric), at=still_under_limit))
    assert r2.incident_transitions == ()

    over_limit = T0 + timedelta(minutes=61)
    r3 = pipeline.process(batch(snapshot(at=over_limit, context=electric), at=over_limit))
    assert [t.transition_type for t in r3.incident_transitions] == [IncidentTransitionType.OPEN]
    assert r3.incident_transitions[0].incident.key.rule_code == "EV_OVERSTAY"

    exiting_at = over_limit + timedelta(seconds=1)
    r4 = pipeline.process(batch(snapshot(bbox=OUTSIDE_BBOX, at=exiting_at, context=electric), at=exiting_at))
    assert r4.incident_transitions == ()  # EXITING — 아직 안 닫힘

    exited_at = exiting_at + timedelta(seconds=1)
    r5 = pipeline.process(batch(snapshot(bbox=OUTSIDE_BBOX, at=exited_at, context=electric), at=exited_at))
    assert [t.transition_type for t in r5.incident_transitions] == [IncidentTransitionType.RESOLVE]
    assert r5.incident_transitions[0].incident.incident_id == r3.incident_transitions[0].incident.incident_id


def test_ev_overstay_never_confirms_without_allowed_minutes():
    """구역에 allowed_minutes가 없으면 아무리 오래 점유해도 EV_OVERSTAY가
    확정되지 않는다."""
    unlimited_zone = ParkingZone(
        zone_id=4,
        zone_number="EV-02",
        zone_type=ZoneType.EV_SLOW,
        polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
        allowed_minutes=None,
    )
    pipeline = make_pipeline(zones=(unlimited_zone,))
    electric = VehicleContext(parking_session_id=1, vehicle_id=1, is_electric=True, is_disabled_vehicle=False)

    pipeline.process(batch(snapshot(at=T0, context=electric), at=T0))
    pipeline.process(batch(snapshot(at=T0 + timedelta(seconds=1), context=electric), at=T0 + timedelta(seconds=1)))
    long_after = T0 + timedelta(days=1)
    r = pipeline.process(batch(snapshot(at=long_after, context=electric), at=long_after))

    assert r.incident_transitions == ()


def test_ended_vehicle_that_never_visited_a_zone_produces_no_transitions():
    """구역을 한 번도 안 밟은 채 사라진 차량은 아무 사건도 만들지 않는다.

    446 전에는 이 시나리오가 `_last_snapshot`이라는 캐시가 무한히 커지지
    않는지를 검증하는 테스트였다 — 그 캐시 자체가 버그의 원인이라 삭제했으므로
    (해소 판정이 이제 스냅샷을 아예 안 쓴다), 지금은 그냥 아무 전이도 없다는
    것만 확인한다."""
    pipeline = make_pipeline()
    passerby = snapshot(bbox=OUTSIDE_BBOX, at=T0)  # 구역 밖만 지나감, 방문 없음

    pipeline.process(batch(passerby, at=T0))
    r1 = pipeline.process(batch(at=T0 + timedelta(seconds=1), ended=(CAR,)))

    assert r1.incident_transitions == ()

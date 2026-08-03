"""PassthroughEntityResolver의 segment 연결과 runtime reset 계약."""

from datetime import datetime, timezone
from uuid import UUID

from src.tracking.entity_resolver import PassthroughEntityResolver
from src.tracking.models import BoundingBox, TrackObservation, TrackSegmentId


OBSERVED_AT = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BBOX = BoundingBox(0.1, 0.1, 0.2, 0.2)


def _observation(track_segment_id: int) -> TrackObservation:
    return TrackObservation(
        track_segment_id=TrackSegmentId(track_segment_id),
        bbox=BBOX,
        confidence=0.9,
        observed_at=OBSERVED_AT,
    )


def test_resolve_keeps_one_physical_id_while_track_segment_is_attached():
    resolver = PassthroughEntityResolver()

    first = resolver.resolve(_observation(1))
    second = resolver.resolve(_observation(1))

    assert first == second
    assert isinstance(first, UUID)


def test_different_track_segment_ids_get_different_physical_ids():
    resolver = PassthroughEntityResolver()

    assert resolver.resolve(_observation(1)) != resolver.resolve(_observation(2))


def test_not_calling_end_for_a_missing_frame_keeps_the_same_identity():
    """현재 frame에 없다는 사실만으로 segment 연결을 해제하지 않는다."""

    resolver = PassthroughEntityResolver()
    first = resolver.resolve(_observation(1))

    # 중간 frame에 track 1을 resolve하지 않았더라도 adapter가 종료를
    # 확정하지 않았으므로 연결은 그대로다.
    again = resolver.resolve(_observation(1))

    assert again == first


def test_end_track_segments_detaches_only_explicit_ids():
    resolver = PassthroughEntityResolver()
    first = resolver.resolve(_observation(1))
    second = resolver.resolve(_observation(2))

    result = resolver.end_track_segments({TrackSegmentId(2)})

    assert result is None
    assert resolver.resolve(_observation(1)) == first
    assert resolver.resolve(_observation(2)) != second


def test_end_track_segments_is_idempotent_for_already_detached_id():
    resolver = PassthroughEntityResolver()
    previous = resolver.resolve(_observation(1))

    first_call = resolver.end_track_segments({TrackSegmentId(1)})
    second_call = resolver.end_track_segments({TrackSegmentId(1)})

    assert first_call is None
    assert second_call is None
    assert resolver.resolve(_observation(1)) != previous


def test_reappearing_segment_id_after_confirmed_end_gets_new_physical_id():
    """재식별 없는 통과 구현의 명시적 한계를 고정한다."""

    resolver = PassthroughEntityResolver()
    first = resolver.resolve(_observation(1))
    resolver.end_track_segments({TrackSegmentId(1)})

    again = resolver.resolve(_observation(1))

    assert again != first
    assert isinstance(again, UUID)


def test_forget_physical_vehicle_detaches_all_remaining_segments():
    resolver = PassthroughEntityResolver()
    first = resolver.resolve(_observation(1))
    second = resolver.resolve(_observation(2))

    result = resolver.forget_physical_vehicle(first)

    assert result is None
    assert resolver.resolve(_observation(1)) != first
    assert resolver.resolve(_observation(2)) == second


def test_reset_track_segments_discards_all_runtime_numeric_id_bindings():
    resolver = PassthroughEntityResolver()
    first = resolver.resolve(_observation(1))
    second = resolver.resolve(_observation(2))

    result = resolver.reset_track_segments()

    assert result is None
    assert resolver.resolve(_observation(1)) != first
    assert resolver.resolve(_observation(2)) != second

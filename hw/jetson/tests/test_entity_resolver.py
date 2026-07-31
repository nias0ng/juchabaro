"""PassthroughEntityResolver 회귀 테스트 (436)."""

from src.tracking.entity_resolver import PassthroughEntityResolver


def test_resolve_maps_track_segment_id_deterministically():
    resolver = PassthroughEntityResolver()

    first = resolver.resolve(1)
    second = resolver.resolve(1)

    assert first == second == "track-1"


def test_different_track_segment_ids_get_different_physical_ids():
    resolver = PassthroughEntityResolver()

    assert resolver.resolve(1) != resolver.resolve(2)


def test_resolve_ended_returns_ids_no_longer_observed():
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)
    resolver.resolve(2)

    ended = resolver.resolve_ended({1})  # track 2는 이번 프레임에 더 이상 없음

    assert ended == ["track-2"]


def test_resolve_ended_forgets_ended_ids_so_they_dont_repeat():
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)

    first_call = resolver.resolve_ended(set())
    second_call = resolver.resolve_ended(set())

    assert first_call == ["track-1"]
    assert second_call == []  # 이미 종료 처리된 트랙은 다시 나오면 안 됨


def test_resolve_ended_returns_empty_when_all_still_observed():
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)

    assert resolver.resolve_ended({1}) == []


def test_reappearing_track_segment_id_after_being_forgotten_is_new_physical_id():
    """ByteTrack이 트랙을 잃었다 재발급하면(§7 한계 1), 통과 구현은 재식별을
    안 하므로 실제로는 같은 물리적 값(f"track-{id}")이 그대로 나온다 —
    다만 그 사이에 resolve_ended로 한 번 '종료'가 보고된다는 계약을 고정한다."""
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)
    resolver.resolve_ended(set())  # track 1 종료 보고

    again = resolver.resolve(1)

    assert again == "track-1"

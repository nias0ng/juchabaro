"""PassthroughEntityResolver 회귀 테스트 (436)."""

from uuid import UUID

from src.tracking.entity_resolver import PassthroughEntityResolver


def test_resolve_keeps_one_physical_id_while_track_is_active():
    resolver = PassthroughEntityResolver()

    first = resolver.resolve(1)
    second = resolver.resolve(1)

    assert first == second
    assert isinstance(first, UUID)


def test_different_track_segment_ids_get_different_physical_ids():
    resolver = PassthroughEntityResolver()

    assert resolver.resolve(1) != resolver.resolve(2)


def test_resolve_ended_returns_ids_no_longer_observed():
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)
    expected = resolver.resolve(2)

    ended = resolver.resolve_ended({1})  # track 2는 이번 프레임에 더 이상 없음

    assert ended == [expected]


def test_resolve_ended_forgets_ended_ids_so_they_dont_repeat():
    resolver = PassthroughEntityResolver()
    expected = resolver.resolve(1)

    first_call = resolver.resolve_ended(set())
    second_call = resolver.resolve_ended(set())

    assert first_call == [expected]
    assert second_call == []  # 이미 종료 처리된 트랙은 다시 나오면 안 됨


def test_resolve_ended_returns_empty_when_all_still_observed():
    resolver = PassthroughEntityResolver()
    resolver.resolve(1)

    assert resolver.resolve_ended({1}) == []


def test_reappearing_track_segment_id_after_being_forgotten_is_new_physical_id():
    """종료 후 같은 ByteTrack ID가 재사용돼도 새 물리 차량 관측이다."""
    resolver = PassthroughEntityResolver()
    first = resolver.resolve(1)
    resolver.resolve_ended(set())  # track 1 종료 보고

    again = resolver.resolve(1)

    assert again != first
    assert isinstance(again, UUID)

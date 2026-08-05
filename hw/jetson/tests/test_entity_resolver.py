"""EntityResolver의 frame 단위 1:1 동일성·보수적 재식별 계약."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

import src.tracking.entity_resolver as resolver_module
from src.tracking.entity_resolver import (
    GeometricEntityResolver,
    PassthroughEntityResolver,
)
from src.tracking.models import (
    BoundingBox,
    IdentityResolution,
    IdentityResolutionBatch,
    IdentityResolutionOutcome,
    IdentityResolutionReason,
    PhysicalVehicleId,
    TrackObservation,
    TrackSegmentId,
)


OBSERVED_AT = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BBOX = BoundingBox(0.1, 0.1, 0.2, 0.2)
NEAR_BBOX = BoundingBox(0.105, 0.1, 0.205, 0.2)
OTHER_BBOX = BoundingBox(0.2, 0.1, 0.3, 0.2)
MIDDLE_BBOX = BoundingBox(0.15, 0.1, 0.25, 0.2)
FAR_BBOX = BoundingBox(0.75, 0.75, 0.85, 0.85)


def _observation(track_segment_id: int) -> TrackObservation:
    return TrackObservation(
        track_segment_id=TrackSegmentId(track_segment_id),
        bbox=BBOX,
        confidence=0.9,
        observed_at=OBSERVED_AT,
    )


def _observation_at(
    track_segment_id: int,
    *,
    bbox: BoundingBox,
    seconds: float,
) -> TrackObservation:
    return TrackObservation(
        track_segment_id=TrackSegmentId(track_segment_id),
        bbox=bbox,
        confidence=0.9,
        observed_at=OBSERVED_AT + timedelta(seconds=seconds),
    )


def _by_segment(batch):
    return {
        int(item.track_segment_id): item for item in batch.resolutions
    }


def _uuid_sequence():
    values = iter(UUID(int=value) for value in range(1, 100))
    return lambda: next(values)


def test_identity_resolution_models_enforce_one_to_one_contract():
    vehicle_id = PhysicalVehicleId(UUID(int=1))
    with pytest.raises(ValueError, match="UNRESOLVED"):
        IdentityResolution(
            track_segment_id=TrackSegmentId(1),
            outcome=IdentityResolutionOutcome.UNRESOLVED,
            physical_vehicle_id=vehicle_id,
            reason=IdentityResolutionReason.AMBIGUOUS_CANDIDATES,
        )

    with pytest.raises(ValueError, match="multiple segments"):
        IdentityResolutionBatch(
            (
                IdentityResolution(
                    track_segment_id=TrackSegmentId(1),
                    outcome=IdentityResolutionOutcome.CREATED,
                    physical_vehicle_id=vehicle_id,
                ),
                IdentityResolution(
                    track_segment_id=TrackSegmentId(2),
                    outcome=IdentityResolutionOutcome.REIDENTIFIED,
                    physical_vehicle_id=vehicle_id,
                ),
            )
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


def test_passthrough_frame_mapping_is_input_order_independent(monkeypatch):
    items = (
        _observation_at(1, bbox=BBOX, seconds=0),
        _observation_at(2, bbox=OTHER_BBOX, seconds=0),
    )

    def run(observations):
        monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
        batch = PassthroughEntityResolver().resolve_frame(
            observations,
            ended_track_segment_ids=set(),
        )
        return {
            int(item.track_segment_id): item.physical_vehicle_id
            for item in batch.resolutions
        }

    assert run(items) == run(tuple(reversed(items)))


def test_ended_segment_is_reidentified_atomically_in_the_same_frame(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=1.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    created = resolver.resolve_frame(
        (_observation_at(1, bbox=BBOX, seconds=0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]

    reidentified = resolver.resolve_frame(
        (_observation_at(2, bbox=NEAR_BBOX, seconds=0.5),),
        ended_track_segment_ids={TrackSegmentId(1)},
    ).resolutions[0]

    assert reidentified.outcome is IdentityResolutionOutcome.REIDENTIFIED
    assert reidentified.physical_vehicle_id == created.physical_vehicle_id
    assert reidentified.gap_seconds == pytest.approx(0.5)


def test_configured_window_reidentifies_multisecond_pilot_gap(monkeypatch):
    """일반 구역 조작 뒤 관측된 약 3초대 ID switch를 같은 차량으로 잇는다."""

    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=4.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    created = resolver.resolve_frame(
        (_observation_at(1, bbox=BBOX, seconds=0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]

    reidentified = resolver.resolve_frame(
        (_observation_at(2, bbox=NEAR_BBOX, seconds=3.2),),
        ended_track_segment_ids={TrackSegmentId(1)},
    ).resolutions[0]

    assert reidentified.outcome is IdentityResolutionOutcome.REIDENTIFIED
    assert reidentified.physical_vehicle_id == created.physical_vehicle_id
    assert reidentified.gap_seconds == pytest.approx(3.2)


def test_far_or_late_segment_creates_a_new_identity(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=1.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    first = resolver.resolve_frame(
        (_observation_at(1, bbox=BBOX, seconds=0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]
    far = resolver.resolve_frame(
        (_observation_at(2, bbox=FAR_BBOX, seconds=0.5),),
        ended_track_segment_ids={TrackSegmentId(1)},
    ).resolutions[0]
    late = resolver.resolve_frame(
        (_observation_at(3, bbox=BBOX, seconds=2.0),),
        ended_track_segment_ids={TrackSegmentId(2)},
    ).resolutions[0]

    assert far.outcome is IdentityResolutionOutcome.CREATED
    assert late.outcome is IdentityResolutionOutcome.CREATED
    assert first.physical_vehicle_id not in {
        far.physical_vehicle_id,
        late.physical_vehicle_id,
    }


def _run_ordered_reidentification(monkeypatch, *, reverse: bool):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=1.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    seeds = (
        _observation_at(1, bbox=BBOX, seconds=0),
        _observation_at(2, bbox=OTHER_BBOX, seconds=0),
    )
    replacements = (
        _observation_at(11, bbox=NEAR_BBOX, seconds=0.5),
        _observation_at(12, bbox=OTHER_BBOX, seconds=0.5),
    )
    if reverse:
        seeds = tuple(reversed(seeds))
        replacements = tuple(reversed(replacements))
    created = _by_segment(
        resolver.resolve_frame(seeds, ended_track_segment_ids=set())
    )
    resolved = _by_segment(
        resolver.resolve_frame(
            replacements,
            ended_track_segment_ids={TrackSegmentId(1), TrackSegmentId(2)},
        )
    )
    return (
        {
            segment: item.physical_vehicle_id
            for segment, item in created.items()
        },
        {
            segment: (item.outcome, item.physical_vehicle_id)
            for segment, item in resolved.items()
        },
    )


def test_geometric_resolution_is_independent_of_observation_order(monkeypatch):
    forward = _run_ordered_reidentification(monkeypatch, reverse=False)
    reverse = _run_ordered_reidentification(monkeypatch, reverse=True)

    assert forward == reverse
    created, resolved = forward
    assert resolved == {
        11: (IdentityResolutionOutcome.REIDENTIFIED, created[1]),
        12: (IdentityResolutionOutcome.REIDENTIFIED, created[2]),
    }


def test_ambiguous_observation_does_not_mutate_identity_history(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=3.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    seeds = _by_segment(
        resolver.resolve_frame(
            (
                _observation_at(1, bbox=BBOX, seconds=0),
                _observation_at(2, bbox=OTHER_BBOX, seconds=0),
            ),
            ended_track_segment_ids=set(),
        )
    )

    ambiguous_input = (
        _observation_at(3, bbox=MIDDLE_BBOX, seconds=1.0),
    )
    ambiguous = resolver.resolve_frame(
        ambiguous_input,
        ended_track_segment_ids={TrackSegmentId(1), TrackSegmentId(2)},
    ).resolutions[0]
    repeated = resolver.resolve_frame(
        ambiguous_input,
        ended_track_segment_ids=set(),
    ).resolutions[0]

    assert ambiguous.outcome is IdentityResolutionOutcome.UNRESOLVED
    assert ambiguous.reason is IdentityResolutionReason.AMBIGUOUS_CANDIDATES
    assert repeated == ambiguous

    recovered = resolver.resolve_frame(
        (_observation_at(3, bbox=BBOX, seconds=2.0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]
    assert recovered.outcome is IdentityResolutionOutcome.REIDENTIFIED
    assert recovered.physical_vehicle_id == seeds[1].physical_vehicle_id


def test_continuing_vehicle_cannot_be_selected_by_a_second_segment(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(
        max_gap_seconds=3.0,
        minimum_score=0.42,
        ambiguity_margin=0.08,
    )
    created = resolver.resolve_frame(
        (_observation_at(1, bbox=BBOX, seconds=0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]

    frame = _by_segment(
        resolver.resolve_frame(
            (
                _observation_at(1, bbox=BBOX, seconds=1.0),
                _observation_at(3, bbox=BBOX, seconds=1.0),
            ),
            ended_track_segment_ids=set(),
        )
    )

    assert frame[1].outcome is IdentityResolutionOutcome.CONTINUED
    assert frame[1].physical_vehicle_id == created.physical_vehicle_id
    assert frame[3].outcome is IdentityResolutionOutcome.UNRESOLVED
    assert frame[3].reason is (
        IdentityResolutionReason.CANDIDATE_ALREADY_OCCUPIED
    )

    recovered = resolver.resolve_frame(
        (_observation_at(3, bbox=BBOX, seconds=2.0),),
        ended_track_segment_ids={TrackSegmentId(1)},
    ).resolutions[0]
    assert recovered.outcome is IdentityResolutionOutcome.REIDENTIFIED
    assert recovered.physical_vehicle_id == created.physical_vehicle_id


def test_forget_prevents_terminal_identity_from_being_reidentified(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(max_gap_seconds=1.0)
    created = resolver.resolve_frame(
        (_observation_at(1, bbox=BBOX, seconds=0),),
        ended_track_segment_ids=set(),
    ).resolutions[0]
    resolver.forget_physical_vehicle(created.physical_vehicle_id)

    after_terminal = resolver.resolve_frame(
        (_observation_at(2, bbox=BBOX, seconds=0.5),),
        ended_track_segment_ids={TrackSegmentId(1)},
    ).resolutions[0]

    assert after_terminal.outcome is IdentityResolutionOutcome.CREATED
    assert after_terminal.physical_vehicle_id != created.physical_vehicle_id


def test_frame_failure_rolls_back_earlier_history_and_ended_bindings(monkeypatch):
    monkeypatch.setattr(resolver_module, "uuid4", _uuid_sequence())
    resolver = GeometricEntityResolver(max_gap_seconds=3.0)
    created = _by_segment(
        resolver.resolve_frame(
            (
                _observation_at(1, bbox=BBOX, seconds=1.0),
                _observation_at(2, bbox=OTHER_BBOX, seconds=1.0),
            ),
            ended_track_segment_ids=set(),
        )
    )

    with pytest.raises(ValueError, match="monotonic"):
        resolver.resolve_frame(
            (
                _observation_at(2, bbox=OTHER_BBOX, seconds=0.5),
                _observation_at(3, bbox=FAR_BBOX, seconds=2.0),
            ),
            ended_track_segment_ids={TrackSegmentId(1)},
        )

    retried = _by_segment(
        resolver.resolve_frame(
            (
                _observation_at(1, bbox=BBOX, seconds=1.5),
                _observation_at(2, bbox=OTHER_BBOX, seconds=1.5),
            ),
            ended_track_segment_ids=set(),
        )
    )
    assert retried[1].outcome is IdentityResolutionOutcome.CONTINUED
    assert retried[2].outcome is IdentityResolutionOutcome.CONTINUED
    assert retried[1].physical_vehicle_id == created[1].physical_vehicle_id
    assert retried[2].physical_vehicle_id == created[2].physical_vehicle_id


def _candidate(vehicle_int: int, score: float, creation_order: int):
    return resolver_module._CandidateScore(
        physical_vehicle_id=PhysicalVehicleId(UUID(int=vehicle_int)),
        score=score,
        gap_seconds=0.5,
        center_distance_ratio=0.1,
        predicted_iou=0.5,
        area_ratio=1.0,
        creation_order=creation_order,
    )


def test_maximum_weight_assignment_uses_global_one_to_one_optimum():
    vehicle_1_for_a = _candidate(1, 0.90, 0)
    vehicle_2_for_a = _candidate(2, 0.80, 1)
    vehicle_1_for_b = _candidate(1, 0.85, 0)
    vehicle_2_for_b = _candidate(2, 0.10, 1)

    assignment = resolver_module._maximum_weight_assignment(
        {
            TrackSegmentId(10): (vehicle_1_for_a, vehicle_2_for_a),
            TrackSegmentId(20): (vehicle_1_for_b, vehicle_2_for_b),
        }
    )

    assert {
        int(segment_id): candidate.physical_vehicle_id
        for segment_id, candidate in assignment.selected.items()
    } == {
        10: PhysicalVehicleId(UUID(int=2)),
        20: PhysicalVehicleId(UUID(int=1)),
    }
    assert assignment.score_units == 1_650_000

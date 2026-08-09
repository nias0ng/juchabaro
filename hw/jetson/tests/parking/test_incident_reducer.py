"""IncidentReducer의 삼상태 timer, publication, 직접 종료 계약 테스트."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import (
    BlockingRelationId,
    IncidentKey,
    IncidentRuleTiming,
    IncidentSignal,
    IncidentSignalValue,
    IncidentState,
    IncidentTransitionType,
    IncidentZoneContext,
    ZoneId,
    ZoneVisitId,
)
from src.session.models import EntryAttemptId
from src.tracking.models import ParkingSessionId, PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
OTHER_CAR = PhysicalVehicleId(UUID(int=2))
VICTIM = PhysicalVehicleId(UUID(int=3))
VISIT = ZoneVisitId(UUID(int=101))
RELATION = BlockingRelationId(UUID(int=201))
ATTEMPT = EntryAttemptId(UUID(int=301))
SESSION = ParkingSessionId(401)
TRUSTED_SAMPLE_MAX_GAP_SECONDS = 10.0


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def observed(seconds: float) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at(seconds),
    )


def unknown(seconds: float) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.TRACK_LOST,
        last_reliable_observed_at=at(seconds),
    )


def vehicle_key(rule_code: str = "BAD_PARKING") -> IncidentKey:
    return IncidentKey.for_physical_vehicle(CAR, rule_code)


def visit_key(rule_code: str = "EV_OVERSTAY") -> IncidentKey:
    return IncidentKey.for_zone_visit(VISIT, rule_code)


def relation_key() -> IncidentKey:
    return IncidentKey.for_blocking_relation(RELATION, "DOUBLE_PARKING")


def signal(
    key: IncidentKey,
    value: IncidentSignalValue,
    seconds: float,
    *,
    confirmable: bool = False,
    open_zone_context: IncidentZoneContext | None = None,
) -> IncidentSignal:
    return IncidentSignal(
        key=key,
        value=value,
        confirmable=confirmable,
        observed_at=at(seconds),
        open_zone_context=open_zone_context,
    )


def reduce(
    reducer: InMemoryIncidentReducer,
    key: IncidentKey,
    value: IncidentSignalValue,
    seconds: float,
    *,
    confirmable: bool = False,
    physical_vehicle_id: PhysicalVehicleId = CAR,
    observation: ObservationStatus | None = None,
    entry_attempt_id: EntryAttemptId | None = ATTEMPT,
    entry_time: datetime | None = None,
    parking_session_id: ParkingSessionId | None = None,
    zone_id: ZoneId | None = None,
    victim_physical_vehicle_id: PhysicalVehicleId | None = None,
    open_zone_context: IncidentZoneContext | None = None,
):
    return reducer.reduce(
        signal(
            key,
            value,
            seconds,
            confirmable=confirmable,
            open_zone_context=open_zone_context,
        ),
        physical_vehicle_id=physical_vehicle_id,
        observation=observation or observed(seconds),
        entry_attempt_id=entry_attempt_id,
        entry_time=entry_time,
        parking_session_id=parking_session_id,
        zone_id=zone_id,
        victim_physical_vehicle_id=victim_physical_vehicle_id,
    )


def test_trusted_sample_max_gap_must_be_positive() -> None:
    for invalid_gap in (0, 0.0000001, 0.0000006):
        with pytest.raises(ValueError, match="trusted_sample_max_gap_seconds"):
            InMemoryIncidentReducer(trusted_sample_max_gap_seconds=invalid_gap)


def test_bad_parking_zone_context_latches_only_on_open_and_stays_immutable() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=2.0,
    )
    first_context = IncidentZoneContext(
        zone_id=ZoneId(10),
        related_zone_ids=(ZoneId(11),),
    )
    open_context = IncidentZoneContext(
        zone_id=ZoneId(20),
        related_zone_ids=(ZoneId(21), ZoneId(22)),
    )

    candidate = reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        open_zone_context=first_context,
    ).incident
    assert candidate.state is IncidentState.CANDIDATE
    assert candidate.zone_id is None
    assert candidate.related_zone_ids == ()

    reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
        open_zone_context=open_context,
    )
    opened_reduction = reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        2,
        confirmable=True,
        open_zone_context=open_context,
    )
    opened = opened_reduction.incident
    assert opened.state is IncidentState.OPEN
    assert opened.zone_id == ZoneId(20)
    assert opened.related_zone_ids == (ZoneId(21), ZoneId(22))

    changed_after_open = reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        3,
        confirmable=True,
        open_zone_context=first_context,
    ).incident
    assert changed_after_open.zone_id == ZoneId(20)
    assert changed_after_open.related_zone_ids == (ZoneId(21), ZoneId(22))


def test_rule_timing_overrides_default_only_for_new_matching_rule() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=1.0,
        clear_duration_seconds=2.0,
        rule_timings=(
            IncidentRuleTiming(
                rule_code="BAD_PARKING",
                confirm_duration_seconds=3.0,
                clear_duration_seconds=4.0,
            ),
        ),
    )

    overridden = reduce(
        reducer,
        vehicle_key("BAD_PARKING"),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
    ).incident
    fallback = reduce(
        reducer,
        vehicle_key("OUT_OF_ZONE"),
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
    ).incident

    assert overridden.confirm_duration_seconds == 3.0
    assert overridden.clear_duration_seconds == 4.0
    assert fallback.confirm_duration_seconds == 1.0
    assert fallback.clear_duration_seconds == 2.0


def test_restored_incident_keeps_snapshotted_timing_after_policy_change() -> None:
    original = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        rule_timings=(
            IncidentRuleTiming(
                rule_code="BAD_PARKING",
                confirm_duration_seconds=5.0,
                clear_duration_seconds=6.0,
            ),
        ),
    )
    candidate = reduce(
        original,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
    ).incident
    changed = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=8.0,
        clear_duration_seconds=9.0,
    )
    changed.restore_active((candidate,))

    continued = reduce(
        changed,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
    ).incident

    assert continued.confirm_duration_seconds == 5.0
    assert continued.clear_duration_seconds == 6.0


def test_duplicate_rule_timing_is_rejected() -> None:
    timing = IncidentRuleTiming(
        rule_code="BAD_PARKING",
        confirm_duration_seconds=0.0,
        clear_duration_seconds=0.0,
    )

    with pytest.raises(ValueError, match="duplicate Incident timing"):
        InMemoryIncidentReducer(
            trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
            rule_timings=(timing, timing),
        )


def test_confirm_timer_opens_once_after_consecutive_trusted_samples() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()

    first = reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    middle = reduce(reducer, key, IncidentSignalValue.MATCHED, 3, confirmable=True)
    opened = reduce(reducer, key, IncidentSignalValue.MATCHED, 5, confirmable=True)
    repeated = reduce(reducer, key, IncidentSignalValue.MATCHED, 6, confirmable=True)

    assert first.incident.state is IncidentState.CANDIDATE
    assert first.incident.confirm_trusted_seconds == 0
    assert middle.incident.confirm_trusted_seconds == 3
    assert opened.incident.state is IncidentState.OPEN
    assert opened.incident.confirmed_at == at(5)
    assert opened.incident.publication_revision == 1
    assert opened.transitions[0].transition_type is IncidentTransitionType.OPEN
    assert repeated.incident.state is IncidentState.OPEN
    assert repeated.transitions == ()


def test_restored_incident_does_not_count_process_downtime() -> None:
    original = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()
    checkpoint = reduce(
        original,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
    ).incident
    restored = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    restored.restore_active((checkpoint,))

    resumed = reduce(
        restored,
        key,
        IncidentSignalValue.MATCHED,
        100,
        confirmable=True,
    )
    opened = reduce(
        restored,
        key,
        IncidentSignalValue.MATCHED,
        105,
        confirmable=True,
    )

    assert resumed.incident.confirm_trusted_seconds == 0.0
    assert opened.incident.state is IncidentState.OPEN
    assert opened.incident.confirm_trusted_seconds == 5.0


def test_confirm_timer_does_not_count_a_sample_gap_above_the_limit() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=2,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()

    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    progress = reduce(
        reducer, key, IncidentSignalValue.MATCHED, 2, confirmable=True
    )
    after_gap = reduce(
        reducer, key, IncidentSignalValue.MATCHED, 10, confirmable=True
    )
    resumed = reduce(
        reducer, key, IncidentSignalValue.MATCHED, 12, confirmable=True
    )
    opened = reduce(
        reducer, key, IncidentSignalValue.MATCHED, 13, confirmable=True
    )

    assert progress.incident.confirm_trusted_seconds == 2
    assert after_gap.incident.confirm_trusted_seconds == 2
    assert resumed.incident.confirm_trusted_seconds == 4
    assert opened.incident.state is IncidentState.OPEN


def test_nonconfirmable_match_does_not_advance_candidate_timer() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()

    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    waiting = reduce(reducer, key, IncidentSignalValue.MATCHED, 2, confirmable=False)
    resumed = reduce(reducer, key, IncidentSignalValue.MATCHED, 4, confirmable=True)
    opened = reduce(reducer, key, IncidentSignalValue.MATCHED, 9, confirmable=True)

    assert waiting.incident.confirm_trusted_seconds == 0
    assert resumed.incident.confirm_trusted_seconds == 0
    assert opened.incident.state is IncidentState.OPEN


def test_unknown_pauses_without_resetting_accumulated_confirm_time() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()

    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    progress = reduce(reducer, key, IncidentSignalValue.MATCHED, 3, confirmable=True)
    paused = reduce(
        reducer,
        key,
        IncidentSignalValue.UNKNOWN,
        5,
        observation=observed(5),
    )
    resumed = reduce(reducer, key, IncidentSignalValue.MATCHED, 10, confirmable=True)
    opened = reduce(reducer, key, IncidentSignalValue.MATCHED, 12, confirmable=True)

    assert progress.incident.confirm_trusted_seconds == 3
    assert paused.incident.state is IncidentState.CANDIDATE
    assert paused.incident.observation.state is ObservationState.UNKNOWN
    assert resumed.incident.confirm_trusted_seconds == 3
    assert opened.incident.state is IncidentState.OPEN


def test_unreliable_observation_turns_matched_signal_into_pause() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    result = reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        observation=unknown(0),
    )
    assert result is None
    assert reducer.snapshot() == ()


def test_not_matched_cancels_candidate_but_keeps_terminal_snapshot() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=10,
    )
    key = vehicle_key()
    candidate = reduce(
        reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True
    )
    canceled = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)

    assert canceled.incident.incident_id == candidate.incident.incident_id
    assert canceled.incident.state is IncidentState.CANCELED
    assert canceled.incident.terminated_at == at(1)
    assert canceled.transitions == ()
    assert reducer.active_snapshot() == ()
    assert reducer.snapshot() == (canceled.incident,)


def test_local_only_open_materializes_when_late_correlation_arrives() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    key = vehicle_key()

    local = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        entry_attempt_id=None,
    )
    published = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
        entry_attempt_id=None,
        entry_time=at(0),
        parking_session_id=SESSION,
    )

    assert local.incident.state is IncidentState.OPEN
    assert local.incident.publication_revision == 0
    assert local.transitions == ()
    assert published.incident.incident_id == local.incident.incident_id
    assert published.incident.publication_revision == 1
    assert published.incident.parking_session_id == SESSION
    assert published.transitions[0].transition_type is IncidentTransitionType.OPEN


def test_pre_entry_open_is_not_materialized_by_late_correlation() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    key = vehicle_key()
    local = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        entry_attempt_id=None,
    )

    correlated = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
        entry_time=at(0.5),
        parking_session_id=SESSION,
    )

    assert local.incident.confirmed_at == at(0)
    assert correlated.incident.parking_session_id == SESSION
    assert correlated.incident.publication_revision == 0
    assert correlated.transitions == ()


def test_late_correlation_does_not_drop_same_sample_clear_result() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=10,
        clear_duration_seconds=0,
    )
    key = vehicle_key()
    local = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        entry_attempt_id=None,
    )

    resolved = reduce(
        reducer,
        key,
        IncidentSignalValue.NOT_MATCHED,
        1,
        entry_attempt_id=None,
        parking_session_id=SESSION,
    )

    assert local.incident.publication_revision == 0
    assert resolved.incident.state is IncidentState.RESOLVED
    assert [item.transition_type for item in resolved.transitions] == [
        IncidentTransitionType.OPEN,
        IncidentTransitionType.RESOLVE,
    ]
    assert [item.incident.publication_revision for item in resolved.transitions] == [
        1,
        2,
    ]


def test_late_correlation_materializes_open_from_clear_pending() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=10,
        clear_duration_seconds=5,
    )
    key = vehicle_key()
    reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        entry_attempt_id=None,
    )
    local_clearing = reduce(
        reducer,
        key,
        IncidentSignalValue.NOT_MATCHED,
        1,
        entry_attempt_id=None,
    )

    materialized = reduce(
        reducer,
        key,
        IncidentSignalValue.NOT_MATCHED,
        2,
        entry_attempt_id=None,
        parking_session_id=SESSION,
    )

    assert local_clearing.incident.state is IncidentState.CLEAR_PENDING
    assert local_clearing.incident.publication_revision == 0
    assert materialized.incident.state is IncidentState.CLEAR_PENDING
    assert materialized.incident.publication_revision == 1
    assert [item.transition_type for item in materialized.transitions] == [
        IncidentTransitionType.OPEN
    ]


def test_clear_pending_unknown_pause_and_match_rebound() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        clear_duration_seconds=5,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)

    clearing = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)
    paused = reduce(reducer, key, IncidentSignalValue.UNKNOWN, 3)
    resumed = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 5)
    rebound = reduce(reducer, key, IncidentSignalValue.MATCHED, 6, confirmable=True)

    assert clearing.incident.state is IncidentState.CLEAR_PENDING
    assert paused.incident.state is IncidentState.CLEAR_PENDING
    assert resumed.incident.clear_trusted_seconds == 0
    assert rebound.incident.state is IncidentState.OPEN
    assert rebound.incident.clear_trusted_seconds == 0
    assert rebound.transitions == ()


def test_clear_timer_resolves_published_incident() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        clear_duration_seconds=5,
    )
    key = vehicle_key()
    opened = reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)
    progress = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 4)
    resolved = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 6)

    assert progress.incident.clear_trusted_seconds == 3
    assert resolved.incident.incident_id == opened.incident.incident_id
    assert resolved.incident.state is IncidentState.RESOLVED
    assert resolved.incident.resolved_at == at(6)
    assert resolved.incident.publication_revision == 2
    assert resolved.transitions[0].transition_type is IncidentTransitionType.RESOLVE


def test_clear_timer_does_not_count_a_sample_gap_above_the_limit() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=2,
        clear_duration_seconds=5,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)

    reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)
    progress = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 3)
    after_gap = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 10)
    resumed = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 12)
    resolved = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 13)

    assert progress.incident.clear_trusted_seconds == 2
    assert after_gap.incident.clear_trusted_seconds == 2
    assert resumed.incident.clear_trusted_seconds == 4
    assert resolved.incident.state is IncidentState.RESOLVED


def test_zero_clear_duration_resolves_on_first_not_matched() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        clear_duration_seconds=0,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    resolved = reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)

    assert resolved.incident.state is IncidentState.RESOLVED
    assert resolved.transitions[0].transition_type is IncidentTransitionType.RESOLVE


def test_local_only_resolution_stays_unpublished() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        clear_duration_seconds=0,
    )
    key = vehicle_key()
    reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        entry_attempt_id=None,
    )
    resolved = reduce(
        reducer,
        key,
        IncidentSignalValue.NOT_MATCHED,
        1,
        entry_attempt_id=None,
    )

    assert resolved.incident.state is IncidentState.RESOLVED
    assert resolved.incident.publication_revision == 0
    assert resolved.transitions == ()


def test_reopen_after_terminal_uses_new_incident_id_and_preserves_history() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        clear_duration_seconds=0,
    )
    key = vehicle_key()
    first = reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    reduce(reducer, key, IncidentSignalValue.NOT_MATCHED, 1)
    second = reduce(reducer, key, IncidentSignalValue.MATCHED, 2, confirmable=True)

    assert second.incident.incident_id != first.incident.incident_id
    assert [item.state for item in reducer.snapshot()] == [
        IncidentState.RESOLVED,
        IncidentState.OPEN,
    ]


def test_zone_visit_direct_termination_cancels_candidate_and_resolves_open() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    candidate = reduce(
        reducer,
        visit_key("EV_OVERSTAY"),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=False,
        zone_id=ZoneId(10),
    )
    opened = reduce(
        reducer,
        visit_key("EV_ZONE_UNAUTHORIZED"),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        zone_id=ZoneId(10),
    )

    results = reducer.terminate_zone_visit(
        VISIT,
        observation=observed(1),
        observed_at=at(1),
    )

    by_id = {result.incident.incident_id: result for result in results}
    assert by_id[candidate.incident.incident_id].incident.state is IncidentState.CANCELED
    assert by_id[candidate.incident.incident_id].transitions == ()
    assert by_id[opened.incident.incident_id].incident.state is IncidentState.RESOLVED
    assert (
        by_id[opened.incident.incident_id].transitions[0].transition_type
        is IncidentTransitionType.RESOLVE
    )
    assert reducer.terminate_zone_visit(
        VISIT, observation=observed(2), observed_at=at(2)
    ) == ()


def test_blocking_relation_direct_termination_resolves_relation_scope() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    opened = reduce(
        reducer,
        relation_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        victim_physical_vehicle_id=VICTIM,
    )

    (resolved,) = reducer.terminate_blocking_relation(
        RELATION,
        observation=observed(1),
        observed_at=at(1),
    )
    assert resolved.incident.incident_id == opened.incident.incident_id
    assert resolved.incident.state is IncidentState.RESOLVED


def test_physical_leave_terminates_subject_and_victim_incidents_only() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    subject = reduce(
        reducer,
        vehicle_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
    )
    relation = reduce(
        reducer,
        relation_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        victim_physical_vehicle_id=VICTIM,
    )
    unrelated_key = IncidentKey.for_physical_vehicle(OTHER_CAR, "OUT_OF_ZONE")
    unrelated = reduce(
        reducer,
        unrelated_key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        physical_vehicle_id=OTHER_CAR,
    )

    subject_results = reducer.terminate_physical_vehicle(
        CAR, observation=observed(1), observed_at=at(1)
    )
    victim_results = reducer.terminate_physical_vehicle(
        VICTIM, observation=observed(2), observed_at=at(2)
    )

    assert {result.incident.incident_id for result in subject_results} == {
        subject.incident.incident_id,
        relation.incident.incident_id,
    }
    assert victim_results == ()
    assert reducer.active_snapshot() == (unrelated.incident,)


@pytest.mark.parametrize(
    ("method_name", "scope_id"),
    [
        ("terminate_zone_visit", VISIT),
        ("terminate_blocking_relation", RELATION),
        ("terminate_physical_vehicle", CAR),
    ],
)
@pytest.mark.parametrize(
    "observation",
    [
        unknown(0),
        ObservationStatus(
            state=ObservationState.DEGRADED,
            reason=ObservationReason.PARTIAL_FRAME,
            last_reliable_observed_at=at(0),
        ),
    ],
)
def test_direct_termination_requires_observed_evidence(
    method_name: str,
    scope_id: object,
    observation: ObservationStatus,
) -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )

    with pytest.raises(ValueError, match="requires OBSERVED"):
        getattr(reducer, method_name)(
            scope_id,
            observation=observation,
            observed_at=at(1),
        )


def test_pause_physical_vehicle_breaks_candidate_sample_chain() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)
    progress = reduce(reducer, key, IncidentSignalValue.MATCHED, 2, confirmable=True)

    (paused,) = reducer.pause_physical_vehicle(
        CAR,
        observation=unknown(4),
        observed_at=at(4),
    )
    resumed = reduce(reducer, key, IncidentSignalValue.MATCHED, 10, confirmable=True)
    opened = reduce(reducer, key, IncidentSignalValue.MATCHED, 13, confirmable=True)

    assert progress.incident.confirm_trusted_seconds == 2
    assert paused.incident.observation.state is ObservationState.UNKNOWN
    assert resumed.incident.confirm_trusted_seconds == 2
    assert opened.incident.state is IncidentState.OPEN


def test_pause_preserves_last_reliable_time_when_input_omits_it() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=5,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 0, confirmable=True)

    (paused,) = reducer.pause_physical_vehicle(
        CAR,
        observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.TRACK_LOST,
        ),
        observed_at=at(1),
    )

    assert paused.incident.observation.last_reliable_observed_at == at(0)


def test_pause_physical_vehicle_also_updates_victim_relation_incident() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS
    )
    opened = reduce(
        reducer,
        relation_key(),
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        victim_physical_vehicle_id=VICTIM,
    )

    (paused,) = reducer.pause_physical_vehicle(
        VICTIM,
        observation=unknown(1),
        observed_at=at(1),
    )

    assert paused.incident.incident_id == opened.incident.incident_id
    assert paused.incident.state is IncidentState.OPEN
    assert paused.incident.observation.state is ObservationState.UNKNOWN
    assert paused.transitions == ()


def test_context_identity_cannot_change_inside_one_incident() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=10,
    )
    key = vehicle_key()
    reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        parking_session_id=SESSION,
    )

    with pytest.raises(ValueError, match="parking_session_id cannot change"):
        reduce(
            reducer,
            key,
            IncidentSignalValue.MATCHED,
            1,
            confirmable=True,
            parking_session_id=ParkingSessionId(999),
        )


def test_physical_vehicle_scope_zone_change_is_not_an_identity_conflict() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=10,
    )
    key = vehicle_key()
    first = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        zone_id=ZoneId(10),
    )
    moved = reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        1,
        confirmable=True,
        zone_id=ZoneId(11),
    )

    # zone은 physical-scope continuity가 아니며 최초 위반 context를 보존한다.
    assert first.incident.zone_id == ZoneId(10)
    assert moved.incident.zone_id == ZoneId(10)


def test_zone_visit_scope_still_rejects_zone_context_change() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=10,
    )
    key = visit_key()
    reduce(
        reducer,
        key,
        IncidentSignalValue.MATCHED,
        0,
        confirmable=True,
        zone_id=ZoneId(10),
    )

    with pytest.raises(ValueError, match="zone_id cannot change"):
        reduce(
            reducer,
            key,
            IncidentSignalValue.MATCHED,
            1,
            confirmable=True,
            zone_id=ZoneId(11),
        )


def test_backward_observation_is_rejected() -> None:
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=TRUSTED_SAMPLE_MAX_GAP_SECONDS,
        confirm_duration_seconds=10,
    )
    key = vehicle_key()
    reduce(reducer, key, IncidentSignalValue.MATCHED, 5, confirmable=True)

    with pytest.raises(ValueError, match="과거"):
        reduce(reducer, key, IncidentSignalValue.MATCHED, 4, confirmable=True)

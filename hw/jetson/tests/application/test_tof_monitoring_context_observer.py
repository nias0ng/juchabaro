from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.tof_monitoring_context_observer import (
    TofMonitoringContextObserver,
    TofMonitoringContextObserverPolicy,
    compose_frame_observers,
)
from src.camera.models import CapturedFrame
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    ParkingPipelineResult,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
)
from src.tracking.models import PhysicalVehicleId, TrackingBatch


T0 = datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(seconds=2)
T4 = T0 + timedelta(seconds=4)
T6 = T0 + timedelta(seconds=6)
T10 = T0 + timedelta(seconds=10)

TARGET_ZONE_ID = ZoneId(7)
OTHER_TARGET_ZONE_ID = ZoneId(8)
UNRELATED_ZONE_ID = ZoneId(99)

VISIT_ID = ZoneVisitId(
    UUID("10000000-0000-4000-8000-000000000001")
)
VEHICLE_ID = PhysicalVehicleId(
    UUID("20000000-0000-4000-8000-000000000001")
)
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("30000000-0000-4000-8000-000000000001")
)


class _Requester:
    def __init__(
        self,
        *,
        errors: list[Exception] | None = None,
    ) -> None:
        self.calls = 0
        self.frame_context_flags: list[bool] = []
        self.errors = list(errors or ())

    def request_after_monitoring_context_change(self) -> None:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)

    def request_after_monitoring_frame_commit(
        self,
        *,
        context_changed: bool = False,
    ) -> None:
        self.frame_context_flags.append(context_changed)
        if not context_changed:
            return

        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)


def _observed(at: datetime = T0) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def _degraded(
    reason: ObservationReason = ObservationReason.TRACK_LOST,
) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=reason,
        last_reliable_observed_at=T0,
    )


def _visit(**changes: object) -> ZoneVisit:
    visit = ZoneVisit(
        visit_id=VISIT_ID,
        physical_vehicle_id=VEHICLE_ID,
        zone_id=TARGET_ZONE_ID,
        zone_definition_version=ZoneDefinitionVersion(1),
        state=ZoneVisitState.INSIDE,
        observation=_observed(),
        entry_trusted_seconds=1.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0 - timedelta(seconds=2),
        updated_at=T0,
        entered_candidate_at=T0 - timedelta(seconds=2),
        entered_at=T0 - timedelta(seconds=1),
    )
    return replace(visit, **changes)


def _entry_match_update() -> EntryMatchAttempt:
    return EntryMatchAttempt(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        match_state=EntryMatchState.PENDING,
        decision_state=EntryDecisionState.REVIEW_PENDING,
        decision_revision=1,
        record_version=1,
        created_at=T0,
        updated_at=T0,
        match_deadline_at=T10,
    )


def _parking_result(
    *visits: ZoneVisit,
) -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=visits,
        parking_episode_updates=(),
        incident_transitions=(),
    )


def _result(
    *visits: ZoneVisit,
    entry_match_updates: tuple[EntryMatchAttempt, ...] = (),
    retired_physical_vehicle_ids: tuple[PhysicalVehicleId, ...] = (),
) -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=_parking_result(*visits),
        retired_physical_vehicle_ids=retired_physical_vehicle_ids,
        entry_match_updates=entry_match_updates,
    )


def _frame() -> CapturedFrame:
    return CapturedFrame(
        camera_id="camera-1",
        frame_id=1,
        captured_at=T0,
        image=object(),
        width=1,
        height=1,
        calibration_id=None,
    )


def _batch() -> TrackingBatch:
    return TrackingBatch(
        camera_id="camera-1",
        frame_id=1,
        observed_at=T0,
        vehicles=(),
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(),
        absence_progress=(),
        observation=_observed(),
        full_area_observed=True,
        all_detections_tracked=True,
    )


def _observer(
    requester: _Requester,
) -> TofMonitoringContextObserver:
    return TofMonitoringContextObserver(
        requester=requester,
        policy=TofMonitoringContextObserverPolicy(
            target_zone_ids=(
                TARGET_ZONE_ID,
                OTHER_TARGET_ZONE_ID,
            ),
            monitoring_freshness_seconds=5.0,
        ),
    )


def _observe(
    observer: TofMonitoringContextObserver,
    result: FrameObservationResult,
) -> None:
    observer(_frame(), _batch(), result)


def test_irrelevant_frame_does_not_request_reevaluation() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result())

    assert requester.calls == 0
    assert requester.frame_context_flags == [False]


def test_first_target_zone_visit_requests_once() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))

    assert requester.calls == 1
    assert requester.frame_context_flags == [True]


def test_observer_sends_heartbeat_and_combines_semantic_change() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result())
    _observe(observer, _result(_visit()))

    assert requester.frame_context_flags == [False, True]
    assert requester.calls == 1


def test_unrelated_zone_visit_does_not_request() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(
        observer,
        _result(_visit(zone_id=UNRELATED_ZONE_ID)),
    )

    assert requester.calls == 0


def test_identical_semantic_visit_does_not_request_again() -> None:
    requester = _Requester()
    observer = _observer(requester)
    visit = _visit()

    _observe(observer, _result(visit))
    _observe(observer, _result(visit))

    assert requester.calls == 1


def test_version_timer_and_continuous_timestamp_changes_do_not_request() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    _observe(
        observer,
        _result(
            _visit(
                observation=_observed(T1),
                entry_trusted_seconds=2.0,
                exit_trusted_seconds=0.5,
                record_version=2,
                updated_at=T1,
            )
        ),
    )

    assert requester.calls == 1


def test_zone_visit_state_change_requests() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    _observe(
        observer,
        _result(
            _visit(
                state=ZoneVisitState.EXITING,
                exit_candidate_at=T1,
                updated_at=T1,
                record_version=2,
            )
        ),
    )

    assert requester.calls == 2


def test_observation_state_and_reason_changes_request() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    _observe(
        observer,
        _result(
            _visit(
                observation=_degraded(ObservationReason.TRACK_LOST),
                updated_at=T1,
                record_version=2,
            )
        ),
    )
    _observe(
        observer,
        _result(
            _visit(
                observation=_degraded(
                    ObservationReason.REIDENTIFICATION_UNCERTAIN
                ),
                updated_at=T2,
                record_version=3,
            )
        ),
    )

    assert requester.calls == 3


def test_terminal_visit_requests_and_removes_tracking_state() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    _observe(
        observer,
        _result(
            _visit(
                state=ZoneVisitState.ENDED,
                ended_at=T2,
                termination_reason="vehicle departed",
                updated_at=T2,
                record_version=2,
            )
        ),
    )

    assert requester.calls == 2
    assert VISIT_ID not in observer._visit_states


def test_target_zone_exit_requests_then_removes_tracking_state() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    moved = _visit(
        zone_id=UNRELATED_ZONE_ID,
        updated_at=T1,
        record_version=2,
    )

    _observe(observer, _result(moved))

    assert requester.calls == 2
    assert VISIT_ID not in observer._visit_states

    _observe(observer, _result(moved))

    assert requester.calls == 2


def test_continuous_reliable_observation_within_freshness_does_not_request() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit(observation=_observed(T0))))
    _observe(
        observer,
        _result(
            _visit(
                observation=_observed(T4),
                updated_at=T4,
                record_version=2,
            )
        ),
    )

    assert requester.calls == 1


def test_reliable_observation_after_freshness_gap_requests_once() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit(observation=_observed(T0))))
    _observe(
        observer,
        _result(
            _visit(
                observation=_observed(T6),
                updated_at=T6,
                record_version=2,
            )
        ),
    )
    _observe(
        observer,
        _result(
            _visit(
                observation=_observed(T10),
                updated_at=T10,
                record_version=3,
            )
        ),
    )

    assert requester.calls == 2


@pytest.mark.parametrize(
    "timestamp",
    [
        T0,
        T0 - timedelta(seconds=1),
    ],
)
def test_equal_or_older_reliable_timestamp_is_not_recovery(
    timestamp: datetime,
) -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit(observation=_observed(T0))))
    _observe(
        observer,
        _result(
            _visit(
                observation=_observed(timestamp),
                updated_at=T1,
                record_version=2,
            )
        ),
    )

    assert requester.calls == 1


def test_entry_match_update_requests() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(
        observer,
        _result(entry_match_updates=(_entry_match_update(),)),
    )

    assert requester.calls == 1


def test_vehicle_retirement_requests_and_removes_visit_state() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))
    _observe(
        observer,
        _result(retired_physical_vehicle_ids=(VEHICLE_ID,)),
    )

    assert requester.calls == 2
    assert VISIT_ID not in observer._visit_states


def test_multiple_reasons_in_one_frame_request_only_once() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(
        observer,
        _result(
            _visit(),
            entry_match_updates=(_entry_match_update(),),
            retired_physical_vehicle_ids=(VEHICLE_ID,),
        ),
    )

    assert requester.calls == 1


def test_failed_visit_signal_is_retried_without_new_change(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = _Requester(errors=[RuntimeError("mailbox unavailable")])
    observer = _observer(requester)

    with caplog.at_level(logging.ERROR):
        _observe(observer, _result(_visit()))

    assert requester.calls == 1
    assert observer._request_pending is True
    assert "stage=reevaluation_signal" in caplog.text
    assert "mailbox unavailable" in caplog.text

    _observe(observer, _result(_visit()))

    assert requester.calls == 2
    assert observer._request_pending is False

    _observe(observer, _result())

    assert requester.calls == 2


def test_failed_entry_match_signal_is_retried_on_empty_result() -> None:
    requester = _Requester(errors=[RuntimeError("temporary failure")])
    observer = _observer(requester)

    _observe(
        observer,
        _result(entry_match_updates=(_entry_match_update(),)),
    )

    assert requester.calls == 1
    assert observer._request_pending is True

    _observe(observer, _result())

    assert requester.calls == 2
    assert observer._request_pending is False

    _observe(observer, _result())

    assert requester.calls == 2


def test_new_changes_are_merged_into_existing_pending_request() -> None:
    requester = _Requester(errors=[RuntimeError("temporary failure")])
    observer = _observer(requester)

    _observe(
        observer,
        _result(entry_match_updates=(_entry_match_update(),)),
    )
    _observe(observer, _result(_visit()))

    assert requester.calls == 2
    assert observer._request_pending is False


def test_invalid_retired_vehicle_item_is_logged_and_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = _Requester()
    observer = _observer(requester)
    invalid_result = replace(
        _result(),
        retired_physical_vehicle_ids=("not-a-vehicle-id",),
    )

    with caplog.at_level(logging.ERROR):
        _observe(observer, invalid_result)

    assert requester.calls == 0
    assert "stage=result_inspection" in caplog.text
    assert "PhysicalVehicleId UUID values" in caplog.text


def test_result_inspection_error_does_not_escape(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = _Requester()
    observer = _observer(requester)

    with caplog.at_level(logging.ERROR):
        observer(_frame(), _batch(), object())

    assert requester.calls == 0
    assert "stage=result_inspection" in caplog.text


def test_state_update_error_does_not_escape(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = _Requester()
    observer = _observer(requester)

    def fail_state_update(plan: object) -> None:
        del plan
        raise RuntimeError("state update failed")

    monkeypatch.setattr(observer, "_commit_plan", fail_state_update)

    with caplog.at_level(logging.ERROR):
        _observe(observer, _result(_visit()))

    assert requester.calls == 0
    assert "stage=state_update" in caplog.text
    assert "state update failed" in caplog.text


def test_tof_failure_does_not_block_composed_overlay_observer() -> None:
    requester = _Requester(errors=[RuntimeError("mailbox unavailable")])
    tof_observer = _observer(requester)
    overlay_calls: list[FrameObservationResult] = []

    def overlay(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch
        overlay_calls.append(result)

    composed = compose_frame_observers(tof_observer, overlay)
    assert composed is not None

    result = _result(_visit())
    composed(_frame(), _batch(), result)

    assert requester.calls == 1
    assert overlay_calls == [result]


def test_overlay_observer_error_preserves_existing_propagation_policy() -> None:
    requester = _Requester()
    tof_observer = _observer(requester)

    def failing_overlay(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch, result
        raise RuntimeError("overlay failed")

    composed = compose_frame_observers(tof_observer, failing_overlay)
    assert composed is not None

    with pytest.raises(RuntimeError, match="overlay failed"):
        composed(_frame(), _batch(), _result())


def test_compose_frame_observers_with_no_observer_returns_none() -> None:
    assert compose_frame_observers(None, None) is None


def test_compose_frame_observers_with_one_observer_returns_same_object() -> None:
    def observer(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch, result

    assert compose_frame_observers(None, observer) is observer


def test_compose_frame_observers_calls_multiple_observers_in_order() -> None:
    calls: list[str] = []

    def first(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch, result
        calls.append("first")

    def second(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch, result
        calls.append("second")

    composed = compose_frame_observers(first, None, second)
    assert composed is not None

    composed(_frame(), _batch(), _result())

    assert calls == ["first", "second"]


def test_observer_boundary_only_invokes_lightweight_request_method() -> None:
    requester = _Requester()
    observer = _observer(requester)

    _observe(observer, _result(_visit()))

    assert requester.calls == 1


@pytest.mark.parametrize(
    "target_zone_ids",
    [
        [TARGET_ZONE_ID],
        {TARGET_ZONE_ID},
        "7",
    ],
)
def test_policy_rejects_non_tuple_target_zone_ids(
    target_zone_ids: object,
) -> None:
    with pytest.raises(
        TypeError,
        match="target_zone_ids must be a tuple",
    ):
        TofMonitoringContextObserverPolicy(
            target_zone_ids=target_zone_ids,
            monitoring_freshness_seconds=5.0,
        )


def test_policy_rejects_boolean_zone_id() -> None:
    with pytest.raises(
        ValueError,
        match="positive integer zone IDs",
    ):
        TofMonitoringContextObserverPolicy(
            target_zone_ids=(True,),
            monitoring_freshness_seconds=5.0,
        )


@pytest.mark.parametrize(
    "freshness",
    [
        True,
        "5",
        None,
    ],
)
def test_policy_rejects_non_numeric_or_boolean_freshness(
    freshness: object,
) -> None:
    with pytest.raises(
        TypeError,
        match="monitoring_freshness_seconds must be a number",
    ):
        TofMonitoringContextObserverPolicy(
            target_zone_ids=(TARGET_ZONE_ID,),
            monitoring_freshness_seconds=freshness,
        )


@pytest.mark.parametrize(
    "freshness",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        0,
        0.0,
        -1,
        -0.1,
    ],
)
def test_policy_rejects_non_finite_or_non_positive_freshness(
    freshness: int | float,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "monitoring_freshness_seconds must be finite and positive"
        ),
    ):
        TofMonitoringContextObserverPolicy(
            target_zone_ids=(TARGET_ZONE_ID,),
            monitoring_freshness_seconds=freshness,
        )


def test_policy_normalizes_integer_freshness_to_float() -> None:
    policy = TofMonitoringContextObserverPolicy(
        target_zone_ids=(TARGET_ZONE_ID,),
        monitoring_freshness_seconds=5,
    )

    assert policy.monitoring_freshness_seconds == 5.0
    assert isinstance(policy.monitoring_freshness_seconds, float)


@pytest.mark.parametrize(
    "target_zone_ids",
    [
        (),
        (ZoneId(0),),
        (ZoneId(-1),),
        (TARGET_ZONE_ID, TARGET_ZONE_ID),
    ],
)
def test_policy_rejects_invalid_target_zone_values(
    target_zone_ids: tuple[ZoneId, ...],
) -> None:
    with pytest.raises(ValueError):
        TofMonitoringContextObserverPolicy(
            target_zone_ids=target_zone_ids,
            monitoring_freshness_seconds=5.0,
        )


@pytest.mark.parametrize(
    "requester",
    [
        object(),
        None,
        SimpleNamespace(
            request_after_monitoring_context_change=None,
        ),
        SimpleNamespace(
            request_after_monitoring_context_change="not-callable",
        ),
    ],
)
def test_observer_rejects_requester_without_callable_signal(
    requester: object,
) -> None:
    policy = TofMonitoringContextObserverPolicy(
        target_zone_ids=(TARGET_ZONE_ID,),
        monitoring_freshness_seconds=5.0,
    )

    with pytest.raises(
        TypeError,
        match=(
            "requester must provide a callable "
            "request_after_monitoring_context_change"
        ),
    ):
        TofMonitoringContextObserver(
            requester=requester,
            policy=policy,
        )


def test_observer_rejects_invalid_policy_dependency() -> None:
    with pytest.raises(
        TypeError,
        match="policy must be TofMonitoringContextObserverPolicy",
    ):
        TofMonitoringContextObserver(
            requester=_Requester(),
            policy=object(),
        )


@pytest.mark.parametrize(
    "observers",
    [
        (object(),),
        (None, "not-callable"),
        (lambda frame, batch, result: None, 123),
    ],
)
def test_compose_frame_observers_rejects_non_callable_input(
    observers: tuple[object, ...],
) -> None:
    with pytest.raises(
        TypeError,
        match=r"observers\[\d+\] must be callable or None",
    ):
        compose_frame_observers(*observers)

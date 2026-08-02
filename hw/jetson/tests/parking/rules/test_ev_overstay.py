"""EV 구역 장기 점유 RuleEvaluator의 삼상태 계약을 검증한다."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    IncidentKey,
    IncidentSignalValue,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.rules.ev_overstay import evaluate
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
)


T0 = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
SQUARE = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))


def observed(at: datetime) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def unknown() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.CAMERA_UNAVAILABLE,
        last_reliable_observed_at=T0,
    )


def make_zone(
    *,
    zone_type: ZoneType = ZoneType.EV_CHARGING,
    allowed_duration_seconds: float | None = 60.0,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(1),
        zone_type=zone_type,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
        allowed_duration_seconds=allowed_duration_seconds,
    )


def make_context(
    *,
    wall_clock_seconds: float = 0.0,
    trusted_occupancy_seconds: float = 0.0,
    zone_type: ZoneType = ZoneType.EV_CHARGING,
    allowed_duration_seconds: float | None = 60.0,
    context_observation: ObservationStatus | None = None,
    vehicle_observation: ObservationStatus | None = None,
    visit_observation: ObservationStatus | None = None,
    visit_state: ZoneVisitState = ZoneVisitState.INSIDE,
) -> RuleContext:
    observed_at = T0 + timedelta(seconds=wall_clock_seconds)
    reliable = observed(observed_at)
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=observed_at,
        camera_id="camera-1",
        observation=vehicle_observation or reliable,
    )
    visit = ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=1)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(1),
        zone_definition_version=ZoneDefinitionVersion(1),
        state=visit_state,
        observation=visit_observation or reliable,
        entry_trusted_seconds=trusted_occupancy_seconds,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=observed_at,
        entered_candidate_at=T0,
        entered_at=T0,
        exit_candidate_at=(observed_at if visit_state is ZoneVisitState.EXITING else None),
    )
    return RuleContext(
        vehicle=vehicle,
        observation=context_observation or reliable,
        session_context=None,
        active_zone_visits=(visit,),
        parking_episode=None,
        parking_assignment=None,
        blocking_relations=(),
        zones=ZoneRegistry(
            (
                make_zone(
                    zone_type=zone_type,
                    allowed_duration_seconds=allowed_duration_seconds,
                ),
            )
        ),
        observed_at=observed_at,
    )


def only_signal(context: RuleContext):
    signals = evaluate(context)
    assert len(signals) == 1
    return signals[0]


def test_occupancy_below_allowed_duration_is_not_matched() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=59.9,
        )
    )

    assert signal.key == IncidentKey.for_zone_visit(
        ZoneVisitId(UUID(int=1)),
        "EV_OVERSTAY",
    )
    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False


def test_occupancy_at_allowed_duration_is_matched_and_confirmable() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=60.0,
        )
    )

    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is True


def test_wall_clock_gap_does_not_count_toward_overstay() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=900.0,
            trusted_occupancy_seconds=45.0,
            allowed_duration_seconds=75.0,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["trustedOccupancySeconds"] == 45.0


def test_missing_allowed_duration_policy_is_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=24 * 60 * 60,
            trusted_occupancy_seconds=24 * 60 * 60,
            allowed_duration_seconds=None,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


@pytest.mark.parametrize(
    ("context_observation", "vehicle_observation", "visit_observation"),
    [
        (unknown(), None, None),
        (None, unknown(), None),
        (None, None, unknown()),
    ],
)
def test_unreliable_current_observation_pauses_as_unknown(
    context_observation: ObservationStatus | None,
    vehicle_observation: ObservationStatus | None,
    visit_observation: ObservationStatus | None,
) -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            context_observation=context_observation,
            vehicle_observation=vehicle_observation,
            visit_observation=visit_observation,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_non_ev_zone_produces_no_overstay_signal() -> None:
    assert evaluate(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            zone_type=ZoneType.GENERAL,
            allowed_duration_seconds=None,
        )
    ) == ()


def test_visit_that_is_not_confirmed_inside_is_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            visit_state=ZoneVisitState.EXITING,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False

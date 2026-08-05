"""BlockingRelation 기반 DOUBLE_PARKING 삼상태 평가를 검증한다."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    IncidentKey,
    IncidentSignalValue,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.rules.double_parking import evaluate
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
SUBJECT = PhysicalVehicleId(UUID(int=1))
VICTIM = PhysicalVehicleId(UUID(int=2))
OTHER = PhysicalVehicleId(UUID(int=3))
RELATION_ID = BlockingRelationId(UUID(int=10))
SQUARE = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))


def observed() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=T0,
    )


def unknown() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.REIDENTIFICATION_UNCERTAIN,
        last_reliable_observed_at=T0,
    )


def make_relation(
    state: BlockingRelationState,
    *,
    subject: PhysicalVehicleId = SUBJECT,
    observation: ObservationStatus | None = None,
) -> BlockingRelation:
    confirmed = state in {
        BlockingRelationState.BLOCKING,
        BlockingRelationState.CLEAR_PENDING,
        BlockingRelationState.RESOLVED,
    }
    terminal = state in {
        BlockingRelationState.RESOLVED,
        BlockingRelationState.CANCELED,
    }
    return BlockingRelation(
        blocking_relation_id=RELATION_ID,
        subject_physical_vehicle_id=subject,
        victim_physical_vehicle_id=VICTIM,
        egress_zone_id=ZoneId(2),
        state=state,
        observation=observation or observed(),
        confirm_trusted_seconds=(2.0 if confirmed else 0.0),
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=2.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
        confirmed_at=(T0 if confirmed else None),
        resolved_at=(T0 if state is BlockingRelationState.RESOLVED else None),
        terminated_at=(T0 if terminal else None),
        termination_reason=("RELATION_TERMINATED" if terminal else None),
    )


def make_context(
    *relations: BlockingRelation,
    observation: ObservationStatus | None = None,
) -> RuleContext:
    status = observation or observed()
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=SUBJECT,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="camera-1",
        observation=status,
    )
    aisle = ZoneDefinition(
        zone_id=ZoneId(2),
        zone_type=ZoneType.AISLE,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
    )
    return RuleContext(
        vehicle=vehicle,
        observation=status,
        parking_motion_observation=status,
        session_context=None,
        active_zone_visits=(),
        parking_episode=None,
        parking_assignment=None,
        placement_evidence=None,
        placement_evidence_source=None,
        blocking_relations=relations,
        zones=ZoneRegistry((aisle,)),
        bad_parking_min_primary_overlap_ratio=0.75,
        bad_parking_min_secondary_overlap_ratio=0.25,
        out_of_zone_min_spot_overlap_ratio=0.50,
        observed_at=T0,
    )


def only_signal(context: RuleContext):
    signals = evaluate(context)
    assert len(signals) == 1
    return signals[0]


def test_candidate_relation_matches_but_cannot_confirm_incident() -> None:
    signal = only_signal(
        make_context(make_relation(BlockingRelationState.CANDIDATE))
    )

    assert signal.key == IncidentKey.for_blocking_relation(
        RELATION_ID,
        "DOUBLE_PARKING",
    )
    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is False


def test_confirmed_blocking_relation_is_matched_and_confirmable() -> None:
    signal = only_signal(
        make_context(make_relation(BlockingRelationState.BLOCKING))
    )

    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is True


def test_clear_pending_relation_is_unknown_until_relation_resolves() -> None:
    signal = only_signal(
        make_context(make_relation(BlockingRelationState.CLEAR_PENDING))
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


@pytest.mark.parametrize(
    "state",
    [BlockingRelationState.RESOLVED, BlockingRelationState.CANCELED],
)
def test_terminal_relation_produces_no_rule_signal(
    state: BlockingRelationState,
) -> None:
    assert evaluate(make_context(make_relation(state))) == ()


def test_unknown_relation_observation_pauses_the_predicate() -> None:
    signal = only_signal(
        make_context(
            make_relation(
                BlockingRelationState.BLOCKING,
                observation=unknown(),
            )
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_unknown_frame_observation_pauses_the_predicate() -> None:
    signal = only_signal(
        make_context(
            make_relation(BlockingRelationState.BLOCKING),
            observation=unknown(),
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_relation_owned_by_another_subject_is_not_evaluated() -> None:
    assert evaluate(
        make_context(
            make_relation(
                BlockingRelationState.BLOCKING,
                subject=OTHER,
            )
        )
    ) == ()

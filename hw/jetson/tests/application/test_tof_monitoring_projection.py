from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.application.tof_monitoring_projection import (
    LatestTofMonitoringProjectionStore,
    TofMonitoringProjectionUpdate,
    TofVehicleObservationProjection,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    ZoneDefinitionVersion,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.tracking.models import PhysicalVehicleId


T0 = datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc)
TARGET_ZONE_ID = ZoneId(4)
OTHER_ZONE_ID = ZoneId(99)
VEHICLE_ID = PhysicalVehicleId(UUID(int=1))
VISIT_ID = ZoneVisitId(UUID(int=2))


def _observed(at: datetime = T0) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def _vehicle(
    *,
    physical_vehicle_id: PhysicalVehicleId = VEHICLE_ID,
    observed_at: datetime = T0,
) -> TofVehicleObservationProjection:
    return TofVehicleObservationProjection(
        physical_vehicle_id=physical_vehicle_id,
        observation=_observed(observed_at),
    )


def _visit(**changes: object) -> ZoneVisit:
    visit = ZoneVisit(
        visit_id=VISIT_ID,
        physical_vehicle_id=VEHICLE_ID,
        zone_id=TARGET_ZONE_ID,
        zone_definition_version=ZoneDefinitionVersion(1),
        state=ZoneVisitState.ENTERING,
        observation=_observed(),
        entry_trusted_seconds=0.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
        trusted_sample_max_gap_seconds=1.0,
        entered_candidate_at=T0,
    )
    return replace(visit, **changes)


def _update(
    *,
    frame_id: int = 1,
    observed_at: datetime = T0,
    vehicles: tuple[TofVehicleObservationProjection, ...] | None = None,
    visits: tuple[ZoneVisit, ...] | None = None,
    retired_ids: tuple[PhysicalVehicleId, ...] = (),
) -> TofMonitoringProjectionUpdate:
    return TofMonitoringProjectionUpdate(
        camera_id="camera-1",
        frame_id=frame_id,
        observed_at=observed_at,
        vehicles=(_vehicle(observed_at=observed_at),)
        if vehicles is None
        else vehicles,
        zone_visits=(_visit(observation=_observed(observed_at)),)
        if visits is None
        else visits,
        retired_physical_vehicle_ids=retired_ids,
    )


def _store() -> LatestTofMonitoringProjectionStore:
    return LatestTofMonitoringProjectionStore(
        target_zone_ids=(TARGET_ZONE_ID,),
    )


def test_store_starts_without_a_projection() -> None:
    assert _store().snapshot() is None


def test_store_publishes_latest_vehicle_and_target_visit() -> None:
    store = _store()

    assert store.publish(_update()) is True

    snapshot = store.snapshot()
    assert snapshot is not None
    assert snapshot.frame_id == 1
    assert snapshot.visits_for_zone(TARGET_ZONE_ID) == (_visit(),)
    assert snapshot.vehicle_observation(VEHICLE_ID) == _observed()


def test_store_ignores_duplicate_or_older_frame() -> None:
    store = _store()
    newer = _update(frame_id=2, observed_at=T0 + timedelta(seconds=1))

    assert store.publish(newer) is True
    assert store.publish(_update(frame_id=2, observed_at=newer.observed_at)) is False
    assert store.publish(_update(frame_id=1, observed_at=T0)) is False
    assert store.snapshot() is not None
    assert store.snapshot().frame_id == 2


def test_store_removes_terminal_and_unrelated_zone_visits() -> None:
    store = _store()
    store.publish(_update())
    ended_at = T0 + timedelta(seconds=1)
    terminal = _visit(
        state=ZoneVisitState.CANCELED,
        ended_at=ended_at,
        updated_at=ended_at,
        termination_reason="ENTRY_NOT_CONFIRMED",
    )

    store.publish(
        _update(
            frame_id=2,
            observed_at=ended_at,
            visits=(terminal,),
        )
    )
    snapshot = store.snapshot()
    assert snapshot is not None
    assert snapshot.zone_visits == ()

    store.publish(
        _update(
            frame_id=3,
            observed_at=ended_at + timedelta(seconds=1),
            visits=(_visit(zone_id=OTHER_ZONE_ID),),
        )
    )
    assert store.snapshot() is not None
    assert store.snapshot().zone_visits == ()


def test_store_keeps_last_vehicle_observation_while_visit_is_active() -> None:
    store = _store()
    store.publish(_update())

    store.publish(
        _update(
            frame_id=2,
            observed_at=T0 + timedelta(seconds=1),
            vehicles=(),
            visits=(),
        )
    )

    snapshot = store.snapshot()
    assert snapshot is not None
    assert snapshot.vehicle_observation(VEHICLE_ID) == _observed()
    assert snapshot.visits_for_zone(TARGET_ZONE_ID) == (_visit(),)


def test_store_evicts_retired_vehicle_and_its_visits() -> None:
    store = _store()
    store.publish(_update())

    store.publish(
        _update(
            frame_id=2,
            observed_at=T0 + timedelta(seconds=1),
            vehicles=(),
            visits=(),
            retired_ids=(VEHICLE_ID,),
        )
    )

    snapshot = store.snapshot()
    assert snapshot is not None
    assert snapshot.vehicles == ()
    assert snapshot.zone_visits == ()

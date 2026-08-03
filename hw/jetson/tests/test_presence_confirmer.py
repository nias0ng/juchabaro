"""PhysicalVehicle 미관측·NOT_PRESENT 확정 시간 계약."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.tracking.models import PhysicalVehicleId
from src.tracking.presence_confirmer import PhysicalVehiclePresenceConfirmer


T0 = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
VEHICLE_ID = PhysicalVehicleId(uuid4())
OTHER_VEHICLE_ID = PhysicalVehicleId(uuid4())


def _confirmer(
    *, absence_confirmation_seconds: float = 2.0
) -> PhysicalVehiclePresenceConfirmer:
    return PhysicalVehiclePresenceConfirmer(
        absence_confirmation_seconds=absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=1.0,
    )


def _update(
    confirmer: PhysicalVehiclePresenceConfirmer,
    *,
    seconds: float,
    observed: bool,
    trusted: bool = True,
):
    return confirmer.update(
        observed_physical_vehicle_ids={VEHICLE_ID} if observed else set(),
        observed_at=T0 + timedelta(seconds=seconds),
        trusted_full_area_sample=trusted,
    )


def test_first_negative_sample_starts_at_zero_seconds():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)

    result = _update(confirmer, seconds=10, observed=False)

    assert result.unobserved_physical_vehicle_ids == (VEHICLE_ID,)
    assert result.absence_progress[0].physical_vehicle_id == VEHICLE_ID
    assert result.absence_progress[0].trusted_seconds == 0.0
    assert result.not_present_confirmed_vehicle_ids == ()
    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 0.0


def test_only_elapsed_time_between_consecutive_trusted_negative_samples_counts():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    _update(confirmer, seconds=2, observed=False)

    result = _update(confirmer, seconds=3, observed=False)

    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 2.0
    assert result.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_untrusted_sample_freezes_timer_and_breaks_wall_clock_continuity():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    _update(confirmer, seconds=2, observed=False)

    _update(confirmer, seconds=20, observed=False, trusted=False)
    after_recovery = _update(confirmer, seconds=30, observed=False)
    confirmed = _update(confirmer, seconds=31, observed=False)

    assert after_recovery.not_present_confirmed_vehicle_ids == ()
    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 2.0
    assert confirmed.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_explicit_pause_excludes_camera_downtime_from_elapsed_time():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    _update(confirmer, seconds=2, observed=False)

    confirmer.pause()
    recovered = _update(confirmer, seconds=100, observed=False)

    assert recovered.not_present_confirmed_vehicle_ids == ()
    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 1.0


def test_reobservation_resets_accumulated_absence():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    _update(confirmer, seconds=2, observed=False)

    _update(confirmer, seconds=3, observed=True)
    _update(confirmer, seconds=4, observed=False)
    result = _update(confirmer, seconds=5, observed=False)

    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 1.0
    assert result.not_present_confirmed_vehicle_ids == ()


def test_confirmed_absence_repeats_until_owner_forgets_vehicle():
    """한 frame 처리 실패가 departure 신호를 영구 유실시키지 않는다."""

    confirmer = _confirmer(absence_confirmation_seconds=1.0)
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    first = _update(confirmer, seconds=2, observed=False)
    repeated = _update(confirmer, seconds=3, observed=False)

    confirmer.forget(VEHICLE_ID)
    after_forget = _update(confirmer, seconds=4, observed=False)

    assert first.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert repeated.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert first.absence_progress[0].confirmed_at == T0 + timedelta(seconds=2)
    assert repeated.absence_progress[0].confirmed_at == first.absence_progress[0].confirmed_at
    assert after_forget.not_present_confirmed_vehicle_ids == ()


def test_confirmed_absence_repeats_during_untrusted_sample_until_ack():
    confirmer = _confirmer(absence_confirmation_seconds=1.0)
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)
    confirmed = _update(confirmer, seconds=2, observed=False)

    degraded = _update(confirmer, seconds=3, observed=False, trusted=False)
    recovered = _update(confirmer, seconds=4, observed=False)

    assert confirmed.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert degraded.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert recovered.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert degraded.absence_progress[0].confirmed_at == confirmed.absence_progress[0].confirmed_at
    assert recovered.absence_progress[0].confirmed_at == confirmed.absence_progress[0].confirmed_at


def test_unrelated_new_vehicle_does_not_freeze_missing_vehicle_absence():
    """PresenceConfirmer는 근거 없이 새 ID를 재식별 후보로 추측하지 않는다."""

    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    confirmer.update(
        observed_physical_vehicle_ids={OTHER_VEHICLE_ID},
        observed_at=T0 + timedelta(seconds=1),
        trusted_full_area_sample=True,
    )
    confirmer.update(
        observed_physical_vehicle_ids={OTHER_VEHICLE_ID},
        observed_at=T0 + timedelta(seconds=2),
        trusted_full_area_sample=True,
    )

    confirmed = confirmer.update(
        observed_physical_vehicle_ids={OTHER_VEHICLE_ID},
        observed_at=T0 + timedelta(seconds=3),
        trusted_full_area_sample=True,
    )

    assert confirmed.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_long_gap_between_healthy_samples_breaks_trusted_continuity():
    confirmer = _confirmer()
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)

    after_stall = _update(confirmer, seconds=100, observed=False)

    assert after_stall.not_present_confirmed_vehicle_ids == ()
    assert confirmer.absence_trusted_seconds(VEHICLE_ID) == 0.0


def test_sample_gap_limit_is_independent_from_absence_threshold():
    confirmer = PhysicalVehiclePresenceConfirmer(
        absence_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=2.0,
    )
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=1, observed=False)

    confirmed = _update(confirmer, seconds=2.5, observed=False)

    assert confirmed.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_subsecond_samples_use_persistence_precision_at_threshold() -> None:
    confirmer = PhysicalVehiclePresenceConfirmer(
        absence_confirmation_seconds=10.0,
        trusted_sample_max_gap_seconds=1.0,
    )
    _update(confirmer, seconds=0, observed=True)
    _update(confirmer, seconds=0.1, observed=False)

    result = None
    for index in range(2, 102):
        result = _update(
            confirmer,
            seconds=index / 10,
            observed=False,
        )

    assert result is not None
    assert result.absence_progress[0].trusted_seconds == 10.0
    assert result.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_restored_checkpoint_is_a_lower_bound_without_wall_clock_backfill():
    confirmer = _confirmer(absence_confirmation_seconds=2.0)
    confirmer.restore_checkpoint(
        VEHICLE_ID,
        trusted_seconds=1.0,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        confirmed_at=None,
    )

    after_restart = _update(confirmer, seconds=100, observed=False)
    confirmed = _update(confirmer, seconds=101, observed=False)

    assert after_restart.absence_progress[0].trusted_seconds == 1.0
    assert after_restart.not_present_confirmed_vehicle_ids == ()
    assert confirmed.absence_progress[0].trusted_seconds == 2.0
    assert confirmed.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)


def test_restored_confirmation_repeats_original_occurred_at() -> None:
    confirmer = _confirmer(absence_confirmation_seconds=1.0)
    confirmed_at = T0 + timedelta(seconds=2)
    confirmer.restore_checkpoint(
        VEHICLE_ID,
        trusted_seconds=1.0,
        absence_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        confirmed_at=confirmed_at,
    )

    repeated = _update(confirmer, seconds=100, observed=False)

    assert repeated.not_present_confirmed_vehicle_ids == (VEHICLE_ID,)
    assert repeated.absence_progress[0].confirmed_at == confirmed_at

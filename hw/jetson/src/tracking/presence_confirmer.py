"""PhysicalVehicle의 미관측과 신뢰 가능한 부재 확정을 분리한다.

이 객체는 도메인 timer 정책만 소유한다. camera 장애·부분 frame
구간은 누적하지 않고, SQLite checkpoint와 PhysicalVehicle 종료는
상위 consistency boundary의 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.models import require_aware, require_non_negative, require_positive
from src.tracking.models import (
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleId,
)


@dataclass(frozen=True)
class PresenceConfirmationResult:
    """한 sample에서 미관측된 차량과 현재 부재 확정된 차량."""

    unobserved_physical_vehicle_ids: tuple[PhysicalVehicleId, ...]
    absence_progress: tuple[PhysicalVehicleAbsenceProgress, ...]
    not_present_confirmed_vehicle_ids: tuple[PhysicalVehicleId, ...]


@dataclass
class _AbsenceAccumulator:
    confirmation_microseconds: int
    trusted_sample_max_gap_microseconds: int
    trusted_microseconds: int = 0
    last_trusted_sample_at: datetime | None = None
    confirmed_at: datetime | None = None


class PhysicalVehiclePresenceConfirmer:
    """정상 전체 관측 sample로만 PhysicalVehicle 부재 시간을 누적한다."""

    def __init__(
        self,
        *,
        absence_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
    ) -> None:
        require_positive(absence_confirmation_seconds, "absence_confirmation_seconds")
        require_positive(
            trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if round(absence_confirmation_seconds * 1_000_000) <= 0:
            raise ValueError(
                "absence_confirmation_seconds must be at least one microsecond"
            )
        if round(trusted_sample_max_gap_seconds * 1_000_000) <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        self._default_absence_confirmation_seconds = absence_confirmation_seconds
        self._default_trusted_sample_max_gap_seconds = (
            trusted_sample_max_gap_seconds
        )
        self._accumulators: dict[PhysicalVehicleId, _AbsenceAccumulator] = {}

    def update(
        self,
        *,
        observed_physical_vehicle_ids: set[PhysicalVehicleId],
        observed_at: datetime,
        trusted_full_area_sample: bool,
    ) -> PresenceConfirmationResult:
        """관측 sample 하나를 적용한다.

        첫 미관측 sample은 0초 시작점이다. 관측이 복구되면 누적값을
        0으로 되돌리고, 신뢰할 수 없는 sample은 누적값을 유지하되
        다음 정상 sample에서 장애 구간 wall-clock이 더해지지 않게 한다.
        """

        require_aware(observed_at, "observed_at")
        for physical_vehicle_id in observed_physical_vehicle_ids:
            accumulator = self._accumulators.get(physical_vehicle_id)
            if accumulator is None:
                accumulator = self._new_accumulator()
                self._accumulators[physical_vehicle_id] = accumulator
            accumulator.trusted_microseconds = 0
            accumulator.last_trusted_sample_at = None
            accumulator.confirmed_at = None

        unobserved_ids = set(self._accumulators) - observed_physical_vehicle_ids

        for physical_vehicle_id in unobserved_ids:
            accumulator = self._accumulators[physical_vehicle_id]
            if not trusted_full_area_sample:
                accumulator.last_trusted_sample_at = None
                continue

            last_sample_at = accumulator.last_trusted_sample_at
            if last_sample_at is None:
                accumulator.last_trusted_sample_at = observed_at
                continue
            if observed_at <= last_sample_at:
                continue

            elapsed_microseconds = round(
                (observed_at - last_sample_at).total_seconds() * 1_000_000
            )
            accumulator.last_trusted_sample_at = observed_at
            if (
                elapsed_microseconds
                > accumulator.trusted_sample_max_gap_microseconds
            ):
                # 두 sample 사이의 capture·inference stall을 관측된
                # 시간으로 추정 보충하지 않는다.
                continue

            if accumulator.confirmed_at is not None:
                # 확정 사실은 ACK 전까지 반복하되 완료된 timer를 더
                # 키우지 않아 checkpoint write와 숫자 증가를 멈춘다.
                continue

            accumulator.trusted_microseconds += elapsed_microseconds
            if (
                accumulator.confirmed_at is None
                and accumulator.trusted_microseconds
                >= accumulator.confirmation_microseconds
            ):
                accumulator.confirmed_at = observed_at

        # `confirmed`는 이전의 정상 전체 관측 구간에서 이미 얻은 사실이다.
        # 이후 sample이 불신 상태라는 이유로 그 사실을 숨기면, commit 전에
        # 도착한 늦은 session decision이 차량을 다시 binding할 수 있다.
        # 관측된 차량은 위에서 즉시 reset되므로, 미관측 상태인 확정 사실만
        # 상위 owner의 commit/forget ack까지 반복한다.
        confirmed_ids = {
            physical_vehicle_id
            for physical_vehicle_id in unobserved_ids
            if self._accumulators[physical_vehicle_id].confirmed_at is not None
        }
        return PresenceConfirmationResult(
            unobserved_physical_vehicle_ids=tuple(sorted(unobserved_ids, key=str)),
            absence_progress=tuple(
                PhysicalVehicleAbsenceProgress(
                    physical_vehicle_id=physical_vehicle_id,
                    trusted_seconds=(
                        self._accumulators[
                            physical_vehicle_id
                        ].trusted_microseconds
                        / 1_000_000
                    ),
                    confirmed_at=self._accumulators[
                        physical_vehicle_id
                    ].confirmed_at,
                )
                for physical_vehicle_id in sorted(unobserved_ids, key=str)
            ),
            # 상위 consistency boundary가 PhysicalVehicle 정리를 commit하고
            # forget()으로 ack할 때까지 반복해 한 frame 처리 실패로
            # departure 근거가 유실되지 않게 한다.
            not_present_confirmed_vehicle_ids=tuple(sorted(confirmed_ids, key=str)),
        )

    def restore_checkpoint(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        trusted_seconds: float,
        absence_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
        confirmed_at: datetime | None,
    ) -> None:
        """재식별한 active 차량의 durable absence snapshot을 복원한다.

        마지막 sample 시각은 복원하지 않아 장애 구간 wall-clock을
        더하지 않는다. 진행 중 판단은 차량 생성 당시 scalar를 계속
        사용하며, tracker가 같은 차량을 관측하면 ``update()``가
        복원한 부재를 즉시 reset한다.
        """

        require_non_negative(trusted_seconds, "trusted_seconds")
        require_positive(
            absence_confirmation_seconds,
            "absence_confirmation_seconds",
        )
        require_positive(
            trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        require_aware(confirmed_at, "confirmed_at")
        trusted_microseconds = round(trusted_seconds * 1_000_000)
        confirmation_microseconds = round(
            absence_confirmation_seconds * 1_000_000
        )
        trusted_sample_max_gap_microseconds = round(
            trusted_sample_max_gap_seconds * 1_000_000
        )
        if confirmation_microseconds <= 0:
            raise ValueError(
                "absence_confirmation_seconds must be at least one microsecond"
            )
        if trusted_sample_max_gap_microseconds <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        is_confirmed = trusted_microseconds >= confirmation_microseconds
        if is_confirmed != (confirmed_at is not None):
            raise ValueError(
                "confirmed_at must exist exactly when trusted absence reaches "
                "its confirmation threshold"
            )
        self._accumulators[physical_vehicle_id] = _AbsenceAccumulator(
            confirmation_microseconds=confirmation_microseconds,
            trusted_sample_max_gap_microseconds=(
                trusted_sample_max_gap_microseconds
            ),
            trusted_microseconds=trusted_microseconds,
            last_trusted_sample_at=None,
            confirmed_at=confirmed_at,
        )

    def _new_accumulator(self) -> _AbsenceAccumulator:
        return _AbsenceAccumulator(
            confirmation_microseconds=round(
                self._default_absence_confirmation_seconds * 1_000_000
            ),
            trusted_sample_max_gap_microseconds=round(
                self._default_trusted_sample_max_gap_seconds * 1_000_000
            ),
        )

    def pause(self) -> None:
        """소스 장애·pipeline 중단 이후 wall-clock 합산을 끊는다."""

        for accumulator in self._accumulators.values():
            accumulator.last_trusted_sample_at = None

    def forget(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """상위 owner가 PhysicalVehicle 정리를 commit한 뒤 timer를 제거한다."""

        self._accumulators.pop(physical_vehicle_id, None)

    def absence_trusted_seconds(self, physical_vehicle_id: PhysicalVehicleId) -> float:
        """Checkpoint·진단을 위해 현재 신뢰 누적 초를 반환한다."""

        accumulator = self._accumulators.get(physical_vehicle_id)
        if accumulator is None:
            return 0.0
        return accumulator.trusted_microseconds / 1_000_000

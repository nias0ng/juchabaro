"""10분 연속 정지 정책을 담당하는 주차 에피소드 상태축의 구현 계약.

STATIONARY 관측만 정지 시간에 누적하고 기본 600초에 도달하면 PARKED가 된다.
MOVING은 정지 후보를 초기화하거나 확정된 에피소드를 종료한다. UNKNOWN은
정지 시간에 포함하지 않고 기존 상태도 즉시 종료하지 않는다. 종료 뒤 다시
정지한 차량에는 새로운 parking_episode_id를 발급한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from src.parking.models import ParkingEpisode, ParkingEpisodeId, ParkingState
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
)


class ParkingEpisodeTracker(Protocol):
    """이동 신호를 STOP_PENDING/PARKED/ENDED 에피소드로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observed_at: datetime,
    ) -> ParkingEpisode | None:
        """현재 또는 방금 종료된 에피소드를 반환하고 없으면 None을 반환한다."""

        ...


# 추적이 끊긴 차량의 에피소드를 강제 종료하기까지 기다리는 시간(초).
# ZoneVisitTracker의 같은 이름 상수보다 길다 — 주차 차량은 다른 차에
# 가려 오래 안 보일 수 있고, 성급히 종료하면 열린 사건이 잘못 해소된다.
DEFAULT_STALE_AFTER_SECONDS = 900.0


@dataclass
class _EpisodeSlot:
    """차량 하나의 가변 상태. 외부에는 frozen ParkingEpisode만 내보낸다.

    `accumulated_seconds`는 현재 전이(주차 확정 또는 이동 확인)를 향해 **관측된**
    시간의 합이다. 벽시계 경과가 아니다. `last_observed_at`이 `None`이면 직전에
    UNKNOWN을 만나 누적 사슬이 끊긴 상태이며, 다음 관측은 간격 0을 기여한다.

    `last_updated_at`은 신호 종류와 무관하게 `update()`가 마지막으로 이 슬롯을
    건드린 시각이다. UNKNOWN에 끊기는 `last_observed_at`과 달리 항상 채워져 있어
    `prune()`의 방치 판정 기준이 된다.
    """

    episode: ParkingEpisode
    last_updated_at: datetime
    accumulated_seconds: float = 0.0
    last_observed_at: datetime | None = None
    move_candidate_at: datetime | None = None

    def is_closed(self) -> bool:
        return self.episode.state is ParkingState.ENDED

    def accumulate(self, observed_at: datetime) -> float:
        """직전 관측과의 간격을 누적하고 누적값을 반환한다.

        사슬이 끊겼으면(UNKNOWN 직후) 간격을 더하지 않고 사슬만 다시 잇는다.
        """

        if self.last_observed_at is not None:
            self.accumulated_seconds += (observed_at - self.last_observed_at).total_seconds()
        self.last_observed_at = observed_at
        return self.accumulated_seconds

    def restart(self, observed_at: datetime | None) -> None:
        """누적을 0으로 되돌린다. 상태 전이 직후에 부른다."""

        self.accumulated_seconds = 0.0
        self.last_observed_at = observed_at

    def break_chain(self) -> None:
        """누적 사슬만 끊는다. 이미 쌓인 값은 보존한다 (UNKNOWN 처리)."""

        self.last_observed_at = None


class InMemoryParkingEpisodeTracker:
    """이동 신호를 STOP_PENDING/PARKED/MOVING/ENDED 에피소드로 변환한다.

    상태는 physical_vehicle_id별로 하나다 — 차량 하나는 동시에 두 곳에
    주차할 수 없다. ZoneVisitTracker가 (차량, 구역)별인 것과 다른 점이다.

    STATIONARY 관측만 정지 시간에 누적한다. UNKNOWN은 시간을 누적하지도,
    기존 상태를 초기화하지도 않는다 — 관측이 끊긴 구간을 확정 시간에 넣으면
    카메라 장애가 판정을 바꾼다.
    """

    def __init__(
        self,
        *,
        parked_after_seconds: float,
        move_confirm_seconds: float,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        if parked_after_seconds < 0 or move_confirm_seconds < 0 or stale_after_seconds < 0:
            raise ValueError("임계값은 음수일 수 없습니다.")
        self._parked_after_seconds = parked_after_seconds
        self._move_confirm_seconds = move_confirm_seconds
        self._stale_after_seconds = stale_after_seconds
        self._slots: dict[PhysicalVehicleId, _EpisodeSlot] = {}

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observed_at: datetime,
    ) -> ParkingEpisode | None:
        """현재 또는 방금 종료된 에피소드를 반환한다. 없으면 None을 반환한다."""

        slot = self._slots.get(physical_vehicle_id)
        ensure_forward_observation(
            observed_at, None if slot is None else slot.last_updated_at
        )
        if slot is not None:
            slot.last_updated_at = observed_at

        if slot is None or slot.is_closed():
            if signal is MotionSignal.STATIONARY:
                return self._open_candidate(physical_vehicle_id, parking_session_id, observed_at)
            return None

        if signal is MotionSignal.UNKNOWN:
            # 시간을 누적하지 않고 상태도 바꾸지 않는다. 쌓인 누적은 보존하고
            # 사슬만 끊는다.
            slot.break_chain()
            return slot.episode

        if slot.episode.state is ParkingState.STOP_PENDING:
            return self._advance_stop_pending(slot, signal, observed_at)
        if slot.episode.state is ParkingState.PARKED:
            return self._advance_parked(slot, signal, observed_at)
        if slot.episode.state is ParkingState.MOVING:
            return self._advance_departing(slot, signal, observed_at)
        return slot.episode

    def _open_candidate(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        observed_at: datetime,
    ) -> ParkingEpisode:
        episode = ParkingEpisode(
            episode_id=self._make_episode_id(physical_vehicle_id, observed_at),
            physical_vehicle_id=physical_vehicle_id,
            parking_session_id=parking_session_id,
            state=ParkingState.STOP_PENDING,
            stationary_observed_seconds=0.0,
            last_signal=MotionSignal.STATIONARY,
            last_observed_at=observed_at,
        )
        slot = _EpisodeSlot(
            episode=episode, last_updated_at=observed_at, last_observed_at=observed_at
        )
        self._slots[physical_vehicle_id] = slot
        if self._parked_after_seconds <= 0.0:
            slot.episode = replace(episode, state=ParkingState.PARKED, parked_at=observed_at)
            slot.restart(observed_at)
        return slot.episode

    def _advance_stop_pending(
        self, slot: _EpisodeSlot, signal: MotionSignal, observed_at: datetime
    ) -> ParkingEpisode | None:
        if signal is MotionSignal.MOVING:
            # 확정 전에 움직였다. 후보를 버린다 — 에피소드가 성립하지 않았으므로
            # 종료로 보고하지 않는다.
            del self._slots[slot.episode.physical_vehicle_id]
            return None

        accumulated = slot.accumulate(observed_at)
        slot.episode = replace(
            slot.episode,
            stationary_observed_seconds=accumulated,
            last_signal=signal,
            last_observed_at=observed_at,
        )
        if accumulated >= self._parked_after_seconds:
            slot.episode = replace(
                slot.episode, state=ParkingState.PARKED, parked_at=observed_at
            )
            slot.restart(observed_at)
        return slot.episode

    def _advance_parked(
        self, slot: _EpisodeSlot, signal: MotionSignal, observed_at: datetime
    ) -> ParkingEpisode:
        if signal is MotionSignal.STATIONARY:
            # PARKED에서는 누적할 전이가 없다. 사슬만 이어 둔다.
            slot.last_observed_at = observed_at
            slot.episode = replace(
                slot.episode, last_signal=signal, last_observed_at=observed_at
            )
            return slot.episode

        slot.move_candidate_at = observed_at
        slot.episode = replace(
            slot.episode,
            state=ParkingState.MOVING,
            last_signal=signal,
            last_observed_at=observed_at,
        )
        slot.restart(observed_at)
        if self._move_confirm_seconds <= 0.0:
            slot.episode = replace(
                slot.episode, state=ParkingState.ENDED, ended_at=observed_at
            )
        return slot.episode

    def _advance_departing(
        self, slot: _EpisodeSlot, signal: MotionSignal, observed_at: datetime
    ) -> ParkingEpisode:
        if signal is MotionSignal.STATIONARY:
            # 이동이 확인되지 않았다. 주차 상태로 되돌린다 — parked_at은 유지된다.
            slot.move_candidate_at = None
            slot.episode = replace(
                slot.episode,
                state=ParkingState.PARKED,
                last_signal=signal,
                last_observed_at=observed_at,
            )
            slot.restart(observed_at)
            return slot.episode

        accumulated = slot.accumulate(observed_at)
        slot.episode = replace(
            slot.episode, last_signal=signal, last_observed_at=observed_at
        )
        if accumulated >= self._move_confirm_seconds:
            slot.episode = replace(
                slot.episode,
                state=ParkingState.ENDED,
                # 실제로 움직이기 시작한 시점을 종료 시각으로 쓴다.
                ended_at=slot.move_candidate_at or observed_at,
            )
        return slot.episode

    @staticmethod
    def _make_episode_id(
        physical_vehicle_id: PhysicalVehicleId, stationary_start: datetime
    ) -> ParkingEpisodeId:
        """결정론적 에피소드 ID. uuid4를 쓰면 같은 입력의 두 실행이 달라져
        리플레이 검증이 불가능해진다."""

        return ParkingEpisodeId(f"{physical_vehicle_id}:{stationary_start.isoformat()}")

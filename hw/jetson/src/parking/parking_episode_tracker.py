"""PhysicalVehicle 하나의 연속 정지·주차 행위 수명주기를 관리한다.

정상 관측의 ``STATIONARY``·``MOVING`` sample만 trusted timer에 더한다.
``UNKNOWN`` 또는 degraded 관측은 이미 누적한 하한을 보존한 채 sample 연결만
끊으며 terminal 전이를 만들지 않는다. 실제 출차는 cache timeout이 아니라
상위 owner가 확정한 사실을 ``physical_exit``으로 전달해 처리한다.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Protocol
from uuid import uuid4

from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
)
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import MotionSignal, ParkingSessionId, PhysicalVehicleId


STOP_NOT_CONFIRMED = "STOP_NOT_CONFIRMED"
MOVEMENT_CONFIRMED = "MOVEMENT_CONFIRMED"
PHYSICAL_EXIT = "PHYSICAL_EXIT"

_NON_TERMINAL_STATES = {
    ParkingState.STOP_PENDING,
    ParkingState.PARKED,
    ParkingState.MOVE_PENDING,
}


class ParkingEpisodeTracker(Protocol):
    """신뢰 가능한 motion sample을 ParkingEpisode snapshot으로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
        assignment: ParkingAssignment | None = None,
    ) -> ParkingEpisode | None:
        """현재 snapshot 또는 이번 sample에서 생긴 terminal 전이를 반환한다."""

        ...

    def active_episode(
        self, physical_vehicle_id: PhysicalVehicleId
    ) -> ParkingEpisode | None:
        """PhysicalVehicle의 non-terminal episode를 반환한다."""

        ...

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[ParkingEpisode, ...]:
        """snapshot 없는 관측 공백을 기록하고 trusted timer 연결을 끊는다."""

        ...

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> ParkingEpisode | None:
        """확정된 실제 출차 사실로 active episode를 종료한다."""

        ...

    def checkpoint_state(self) -> object:
        """application transaction 전 rollback checkpoint를 반환한다."""

        ...

    def restore_state(self, checkpoint: object) -> None:
        """commit 실패 전 runtime state로 복구한다."""

        ...

    def restore_active(self, episodes: tuple[ParkingEpisode, ...]) -> None:
        """restart 시 durable nonterminal episode를 끊은 timer chain으로 복원한다."""

        ...


@dataclass
class _EpisodeSlot:
    """frozen domain snapshot과 다음 trusted sample의 연결 지점을 보관한다."""

    episode: ParkingEpisode
    trusted_anchor_at: datetime | None

    def break_chain(self) -> None:
        """누적값은 유지하고 다음 trusted sample과의 시간 연결만 끊는다."""

        self.trusted_anchor_at = None

    def trusted_delta(
        self,
        observed_at: datetime,
        *,
        trusted_sample_max_gap_seconds: float,
    ) -> float:
        """직전 trusted sample 간격을 반환하고 현재 sample을 기준점으로 둔다."""

        delta = 0.0
        if self.trusted_anchor_at is not None:
            delta = (observed_at - self.trusted_anchor_at).total_seconds()
        self.trusted_anchor_at = observed_at
        return delta if delta <= trusted_sample_max_gap_seconds else 0.0


class InMemoryParkingEpisodeTracker:
    """PhysicalVehicle당 최대 하나의 non-terminal ParkingEpisode를 추적한다."""

    def __init__(
        self,
        *,
        parking_confirmation_seconds: float,
        movement_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
    ) -> None:
        if (
            not math.isfinite(parking_confirmation_seconds)
            or parking_confirmation_seconds <= 0
        ):
            raise ValueError("parking_confirmation_seconds must be finite and positive")
        if (
            not math.isfinite(movement_confirmation_seconds)
            or movement_confirmation_seconds < 0
        ):
            raise ValueError(
                "movement_confirmation_seconds must be finite and non-negative"
            )
        if (
            not math.isfinite(trusted_sample_max_gap_seconds)
            or trusted_sample_max_gap_seconds <= 0
            or trusted_sample_max_gap_seconds < 1e-6
        ):
            raise ValueError(
                "trusted_sample_max_gap_seconds must be finite and at least one microsecond"
            )
        self._parking_confirmation_seconds = parking_confirmation_seconds
        self._movement_confirmation_seconds = movement_confirmation_seconds
        self._trusted_sample_max_gap_seconds = trusted_sample_max_gap_seconds
        self._slots: dict[PhysicalVehicleId, _EpisodeSlot] = {}

    def checkpoint_state(self) -> object:
        """mutable slot을 transaction rollback용으로 복사한다."""

        return deepcopy(self._slots)

    def restore_state(self, checkpoint: object) -> None:
        """``checkpoint_state``가 생성한 slot snapshot을 복구한다."""

        if not isinstance(checkpoint, dict):
            raise TypeError("invalid ParkingEpisodeTracker checkpoint")
        self._slots = deepcopy(checkpoint)

    def restore_active(self, episodes: tuple[ParkingEpisode, ...]) -> None:
        """SQLite active snapshot을 wall-clock 보충 없이 복원한다."""

        restored: dict[PhysicalVehicleId, _EpisodeSlot] = {}
        for episode in episodes:
            if episode.state not in _NON_TERMINAL_STATES:
                raise ValueError("only nonterminal ParkingEpisode may be restored")
            if episode.physical_vehicle_id in restored:
                raise ValueError("duplicate active ParkingEpisode restore key")
            restored[episode.physical_vehicle_id] = _EpisodeSlot(
                episode=episode,
                # process downtime을 trusted duration으로 더하지 않는다.
                trusted_anchor_at=None,
            )
        self._slots = restored

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
        assignment: ParkingAssignment | None = None,
    ) -> ParkingEpisode | None:
        """한 motion sample을 적용한다.

        ParkingAssignment는 PARKED로 전이할 때 필수다. episode의
        assignment는 느은 correlation 후에도 원래 PARKED projection을
        재구성할 수 있게 확정 시점 snapshot으로 고정한다.
        """

        if (
            signal is MotionSignal.UNKNOWN
            and observation.state is ObservationState.OBSERVED
        ):
            raise ValueError("UNKNOWN motion signal requires an untrusted observation")

        slot = self._slots.get(physical_vehicle_id)
        ensure_forward_observation(
            observed_at,
            None if slot is None else slot.episode.updated_at,
        )

        if slot is not None and slot.episode.state not in _NON_TERMINAL_STATES:
            del self._slots[physical_vehicle_id]
            slot = None

        if slot is None:
            if not _is_reliable(signal, observation) or signal is not MotionSignal.STATIONARY:
                return None
            return self._open_candidate(
                physical_vehicle_id=physical_vehicle_id,
                parking_session_id=parking_session_id,
                observation=observation,
                observed_at=observed_at,
            )

        previous_episode = slot.episode
        previous_anchor = slot.trusted_anchor_at
        self._bind_session(slot, parking_session_id)
        try:
            if not _is_reliable(signal, observation):
                slot.break_chain()
                slot.episode = self._replace_sample(
                    slot.episode,
                    signal=signal,
                    observation=observation,
                    observed_at=observed_at,
                )
                episode = slot.episode
            elif slot.episode.state is ParkingState.STOP_PENDING:
                episode = self._advance_stop_pending(
                    slot,
                    signal=signal,
                    observation=observation,
                    observed_at=observed_at,
                    assignment=assignment,
                )
            elif slot.episode.state is ParkingState.PARKED:
                episode = self._advance_parked(
                    slot,
                    signal=signal,
                    observation=observation,
                    observed_at=observed_at,
                    assignment=assignment,
                )
            else:
                episode = self._advance_move_pending(
                    slot,
                    signal=signal,
                    observation=observation,
                    observed_at=observed_at,
                    assignment=assignment,
                )

            if episode.state not in _NON_TERMINAL_STATES:
                del self._slots[physical_vehicle_id]
            return episode
        except Exception:
            # 실패한 update의 session late-binding과 timer anchor도 함께 되돌린다.
            slot.episode = previous_episode
            slot.trusted_anchor_at = previous_anchor
            raise

    def active_episode(
        self, physical_vehicle_id: PhysicalVehicleId
    ) -> ParkingEpisode | None:
        """PhysicalVehicle의 non-terminal episode를 side effect 없이 조회한다."""

        slot = self._slots.get(physical_vehicle_id)
        if slot is None or slot.episode.state not in _NON_TERMINAL_STATES:
            return None
        return slot.episode

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[ParkingEpisode, ...]:
        """snapshot 없는 공백 동안 active episode를 유지하고 timer만 멈춘다."""

        slot = self._slots.get(physical_vehicle_id)
        ensure_forward_observation(
            observed_at,
            None if slot is None else slot.episode.updated_at,
        )
        if slot is None or slot.episode.state not in _NON_TERMINAL_STATES:
            return ()

        slot.break_chain()
        slot.episode = replace(
            slot.episode,
            observation=_preserve_last_reliable(
                observation,
                slot.episode.observation,
            ),
            record_version=slot.episode.record_version + 1,
            updated_at=observed_at,
        )
        return (slot.episode,)

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> ParkingEpisode | None:
        """상위 owner가 확정한 실제 출차로 active episode를 terminal로 만든다."""

        slot = self._slots.get(physical_vehicle_id)
        ensure_forward_observation(
            observed_at,
            None if slot is None else slot.episode.updated_at,
        )
        if slot is None or slot.episode.state not in _NON_TERMINAL_STATES:
            return None

        state = (
            ParkingState.CANCELED
            if slot.episode.state is ParkingState.STOP_PENDING
            else ParkingState.ENDED
        )
        exit_observation = ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        )
        terminated = replace(
            slot.episode,
            state=state,
            observation=exit_observation,
            record_version=slot.episode.record_version + 1,
            updated_at=observed_at,
            ended_at=observed_at,
            termination_reason=PHYSICAL_EXIT,
        )
        del self._slots[physical_vehicle_id]
        return terminated

    def _open_candidate(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ParkingEpisode:
        episode = ParkingEpisode(
            episode_id=ParkingEpisodeId(uuid4()),
            physical_vehicle_id=physical_vehicle_id,
            parking_session_id=parking_session_id,
            state=ParkingState.STOP_PENDING,
            observation=observation,
            stationary_trusted_seconds=0.0,
            movement_trusted_seconds=0.0,
            parking_confirmation_seconds=self._parking_confirmation_seconds,
            movement_confirmation_seconds=self._movement_confirmation_seconds,
            last_signal=MotionSignal.STATIONARY,
            record_version=1,
            publication_revision=0,
            created_at=observed_at,
            updated_at=observed_at,
            trusted_sample_max_gap_seconds=self._trusted_sample_max_gap_seconds,
        )
        self._slots[physical_vehicle_id] = _EpisodeSlot(
            episode=episode,
            trusted_anchor_at=observed_at,
        )
        return episode

    def _advance_stop_pending(
        self,
        slot: _EpisodeSlot,
        *,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
        assignment: ParkingAssignment | None,
    ) -> ParkingEpisode:
        if signal is MotionSignal.MOVING:
            slot.trusted_anchor_at = observed_at
            slot.episode = replace(
                slot.episode,
                state=ParkingState.CANCELED,
                observation=observation,
                last_signal=signal,
                record_version=slot.episode.record_version + 1,
                updated_at=observed_at,
                ended_at=observed_at,
                termination_reason=STOP_NOT_CONFIRMED,
            )
            return slot.episode

        delta = (
            0.0
            if slot.trusted_anchor_at is None
            else (observed_at - slot.trusted_anchor_at).total_seconds()
        )
        if delta > slot.episode.trusted_sample_max_gap_seconds:
            delta = 0.0
        trusted = slot.episode.stationary_trusted_seconds + delta
        becomes_parked = trusted >= slot.episode.parking_confirmation_seconds
        if becomes_parked and assignment is None:
            raise ValueError("assignment is required when ParkingEpisode becomes PARKED")

        slot.trusted_anchor_at = observed_at
        slot.episode = replace(
            slot.episode,
            state=ParkingState.PARKED if becomes_parked else ParkingState.STOP_PENDING,
            observation=observation,
            stationary_trusted_seconds=trusted,
            last_signal=signal,
            record_version=slot.episode.record_version + 1,
            updated_at=observed_at,
            assignment=assignment if becomes_parked else None,
            parked_at=observed_at if becomes_parked else None,
            publication_revision=(
                1
                if becomes_parked
                and slot.episode.parking_session_id is not None
                else 0
            ),
        )
        return slot.episode

    def _advance_parked(
        self,
        slot: _EpisodeSlot,
        *,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
        assignment: ParkingAssignment | None,
    ) -> ParkingEpisode:
        slot.trusted_anchor_at = observed_at
        if signal is MotionSignal.STATIONARY:
            slot.episode = replace(
                slot.episode,
                observation=observation,
                last_signal=signal,
                record_version=slot.episode.record_version + 1,
                updated_at=observed_at,
            )
            return slot.episode

        slot.episode = replace(
            slot.episode,
            state=ParkingState.MOVE_PENDING,
            observation=observation,
            movement_trusted_seconds=0.0,
            last_signal=signal,
            record_version=slot.episode.record_version + 1,
            updated_at=observed_at,
            movement_candidate_at=observed_at,
        )
        if slot.episode.movement_confirmation_seconds == 0.0:
            slot.episode = self._end_confirmed_movement(slot.episode, observed_at)
        return slot.episode

    def _advance_move_pending(
        self,
        slot: _EpisodeSlot,
        *,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
        assignment: ParkingAssignment | None,
    ) -> ParkingEpisode:
        if signal is MotionSignal.STATIONARY:
            slot.trusted_anchor_at = observed_at
            slot.episode = replace(
                slot.episode,
                state=ParkingState.PARKED,
                observation=observation,
                movement_trusted_seconds=0.0,
                last_signal=signal,
                record_version=slot.episode.record_version + 1,
                updated_at=observed_at,
                movement_candidate_at=None,
            )
            return slot.episode

        trusted = slot.episode.movement_trusted_seconds + slot.trusted_delta(
            observed_at,
            trusted_sample_max_gap_seconds=(
                slot.episode.trusted_sample_max_gap_seconds
            ),
        )
        slot.episode = replace(
            slot.episode,
            observation=observation,
            movement_trusted_seconds=trusted,
            last_signal=signal,
            record_version=slot.episode.record_version + 1,
            updated_at=observed_at,
        )
        if trusted >= slot.episode.movement_confirmation_seconds:
            slot.episode = self._end_confirmed_movement(slot.episode, observed_at)
        return slot.episode

    @staticmethod
    def _end_confirmed_movement(
        episode: ParkingEpisode,
        observed_at: datetime,
    ) -> ParkingEpisode:
        return replace(
            episode,
            state=ParkingState.ENDED,
            publication_revision=(
                episode.publication_revision + 1
                if episode.publication_revision > 0
                else 0
            ),
            updated_at=observed_at,
            ended_at=observed_at,
            termination_reason=MOVEMENT_CONFIRMED,
        )

    @staticmethod
    def _replace_sample(
        episode: ParkingEpisode,
        *,
        signal: MotionSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ParkingEpisode:
        return replace(
            episode,
            observation=_preserve_last_reliable(observation, episode.observation),
            last_signal=signal,
            record_version=episode.record_version + 1,
            updated_at=observed_at,
        )

    @staticmethod
    def _bind_session(
        slot: _EpisodeSlot,
        parking_session_id: ParkingSessionId | None,
    ) -> None:
        current = slot.episode.parking_session_id
        if current is not None and parking_session_id not in {None, current}:
            raise ValueError("active ParkingEpisode cannot change parking_session_id")
        if current is None and parking_session_id is not None:
            # 같은 update의 record_version 증가에 포함되도록 먼저 값만 병합한다.
            slot.episode = replace(
                slot.episode,
                parking_session_id=parking_session_id,
                publication_revision=(
                    1
                    if slot.episode.state
                    in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
                    else slot.episode.publication_revision
                ),
            )


def _is_reliable(signal: MotionSignal, observation: ObservationStatus) -> bool:
    return signal is not MotionSignal.UNKNOWN and observation.state is ObservationState.OBSERVED


def _preserve_last_reliable(
    observation: ObservationStatus,
    previous: ObservationStatus,
) -> ObservationStatus:
    if observation.last_reliable_observed_at is not None:
        return observation
    return replace(
        observation,
        last_reliable_observed_at=previous.last_reliable_observed_at,
    )

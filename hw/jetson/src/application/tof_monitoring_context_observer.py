"""Monitoring commit 결과에서 ToF 권한 문맥 변경 신호를 생성한다.

이 모듈은 commit된 FrameObservationResult의 의미 있는 변경만 추적하고
ToF authorization mailbox에 가벼운 재평가 신호를 전달한다.

DB 조회, authorization 평가, actuator 명령, Worker lifecycle 및 monitoring
transaction은 이 모듈의 책임이 아니다. Observer 상태는 MonitoringWorker의
단일 frame 처리 thread에서 직렬로 변경된다고 가정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import math
from typing import Protocol
from uuid import UUID

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.monitoring_pipeline import FrameObserver
from src.camera.models import CapturedFrame
from src.domain.models import ObservationReason, ObservationState
from src.parking.models import (
    ParkingPipelineResult,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.session.models import EntryMatchAttempt
from src.tracking.models import PhysicalVehicleId, TrackingBatch


_LOGGER = logging.getLogger(__name__)

_TERMINAL_VISIT_STATES = {
    ZoneVisitState.ENDED,
    ZoneVisitState.CANCELED,
}


class TofMonitoringContextReevaluationRequester(Protocol):
    """ToF authorization 재평가 신호를 받을 최소 application 계약."""

    def request_after_monitoring_context_change(self) -> None:
        """Commit된 monitoring 문맥 변경에 대한 재평가를 요청한다."""

        ...


@dataclass(frozen=True, kw_only=True)
class TofMonitoringContextObserverPolicy:
    """Observer가 추적할 zone과 freshness 회복 기준."""

    target_zone_ids: tuple[ZoneId, ...]
    monitoring_freshness_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.target_zone_ids, tuple):
            raise TypeError("target_zone_ids must be a tuple")
        if not self.target_zone_ids:
            raise ValueError("target_zone_ids must not be empty")
        if any(
            isinstance(zone_id, bool)
            or not isinstance(zone_id, int)
            or zone_id <= 0
            for zone_id in self.target_zone_ids
        ):
            raise ValueError(
                "target_zone_ids must contain positive integer zone IDs"
            )
        if len(self.target_zone_ids) != len(set(self.target_zone_ids)):
            raise ValueError("target_zone_ids must not contain duplicates")

        freshness = self.monitoring_freshness_seconds
        if isinstance(freshness, bool) or not isinstance(
            freshness,
            (int, float),
        ):
            raise TypeError(
                "monitoring_freshness_seconds must be a number"
            )

        normalized_freshness = float(freshness)
        if (
            not math.isfinite(normalized_freshness)
            or normalized_freshness <= 0
        ):
            raise ValueError(
                "monitoring_freshness_seconds must be finite and positive"
            )

        object.__setattr__(
            self,
            "monitoring_freshness_seconds",
            normalized_freshness,
        )


@dataclass(frozen=True)
class _VisitSemanticFingerprint:
    """연속 timestamp나 timer를 제외한 authorization 의미 상태."""

    visit_id: ZoneVisitId
    physical_vehicle_id: PhysicalVehicleId
    zone_id: ZoneId
    state: ZoneVisitState
    observation_state: ObservationState
    observation_reason: ObservationReason | None


@dataclass(frozen=True)
class _TrackedVisitState:
    fingerprint: _VisitSemanticFingerprint
    latest_reliable_observed_at: datetime | None


@dataclass(frozen=True)
class _ObservationPlan:
    visit_states: dict[ZoneVisitId, _TrackedVisitState]
    request_required: bool


class TofMonitoringContextObserver:
    """Commit된 monitoring 결과에서 의미 있는 ToF 재평가 신호만 생성한다.

    신호 전달 실패 시 변경 감지 상태와 별도로 pending 상태를 유지한다.
    따라서 다음 정상 observer 호출에서 새 변경이 없어도 신호를 재시도한다.
    여러 변경과 실패한 요청은 하나의 pending boolean으로 병합된다.
    """

    def __init__(
        self,
        *,
        requester: TofMonitoringContextReevaluationRequester,
        policy: TofMonitoringContextObserverPolicy,
    ) -> None:
        request_method = getattr(
            requester,
            "request_after_monitoring_context_change",
            None,
        )
        if not callable(request_method):
            raise TypeError(
                "requester must provide a callable "
                "request_after_monitoring_context_change"
            )
        if not isinstance(
            policy,
            TofMonitoringContextObserverPolicy,
        ):
            raise TypeError(
                "policy must be TofMonitoringContextObserverPolicy"
            )

        self._requester = requester
        self._policy = policy
        self._target_zone_ids = frozenset(policy.target_zone_ids)
        self._visit_states: dict[
            ZoneVisitId,
            _TrackedVisitState,
        ] = {}
        self._request_pending = False

    def __call__(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        del frame, batch

        try:
            plan = self._inspect_result(result)
        except Exception:
            _LOGGER.exception(
                "ToF monitoring context observer failed "
                "stage=result_inspection"
            )
            return

        try:
            self._commit_plan(plan)
        except Exception:
            _LOGGER.exception(
                "ToF monitoring context observer failed "
                "stage=state_update"
            )
            return

        if not self._request_pending:
            return

        try:
            self._requester.request_after_monitoring_context_change()
        except Exception:
            # 성공적으로 반환된 경우에만 pending을 해제한다.
            _LOGGER.exception(
                "ToF monitoring context observer failed "
                "stage=reevaluation_signal"
            )
            return

        self._request_pending = False

    def _inspect_result(
        self,
        result: FrameObservationResult,
    ) -> _ObservationPlan:
        if not isinstance(result, FrameObservationResult):
            raise TypeError("result must be FrameObservationResult")

        parking_result = result.parking_result
        if not isinstance(parking_result, ParkingPipelineResult):
            raise TypeError(
                "result.parking_result must be ParkingPipelineResult"
            )

        visits = parking_result.zone_visit_updates
        if not isinstance(visits, tuple):
            raise TypeError("zone_visit_updates must be a tuple")
        if any(not isinstance(visit, ZoneVisit) for visit in visits):
            raise TypeError(
                "zone_visit_updates must contain only ZoneVisit values"
            )

        entry_match_updates = result.entry_match_updates
        if not isinstance(entry_match_updates, tuple):
            raise TypeError("entry_match_updates must be a tuple")
        if any(
            not isinstance(update, EntryMatchAttempt)
            for update in entry_match_updates
        ):
            raise TypeError(
                "entry_match_updates must contain only "
                "EntryMatchAttempt values"
            )

        retired_ids = result.retired_physical_vehicle_ids
        if not isinstance(retired_ids, tuple):
            raise TypeError(
                "retired_physical_vehicle_ids must be a tuple"
            )
        # PhysicalVehicleId는 NewType(UUID)이므로 런타임 값은 UUID다.
        if any(
            not isinstance(physical_vehicle_id, UUID)
            for physical_vehicle_id in retired_ids
        ):
            raise TypeError(
                "retired_physical_vehicle_ids must contain "
                "PhysicalVehicleId UUID values"
            )

        next_states = dict(self._visit_states)
        request_required = bool(entry_match_updates or retired_ids)

        for visit in visits:
            current = next_states.get(visit.visit_id)
            targets_current_zone = visit.zone_id in self._target_zone_ids

            if current is None and not targets_current_zone:
                continue

            fingerprint = self._fingerprint(visit)
            reliable_observed_at = self._reliable_observed_at(visit)

            if current is None:
                request_required = True
                latest_reliable_observed_at = reliable_observed_at
            else:
                if current.fingerprint != fingerprint:
                    request_required = True
                if self._freshness_recovered(
                    previous=current.latest_reliable_observed_at,
                    current=reliable_observed_at,
                ):
                    request_required = True

                latest_reliable_observed_at = self._latest_timestamp(
                    current.latest_reliable_observed_at,
                    reliable_observed_at,
                )

            if (
                not targets_current_zone
                or visit.state in _TERMINAL_VISIT_STATES
            ):
                next_states.pop(visit.visit_id, None)
                continue

            next_states[visit.visit_id] = _TrackedVisitState(
                fingerprint=fingerprint,
                latest_reliable_observed_at=(
                    latest_reliable_observed_at
                ),
            )

        if retired_ids:
            retired_id_set = set(retired_ids)
            next_states = {
                visit_id: state
                for visit_id, state in next_states.items()
                if (
                    state.fingerprint.physical_vehicle_id
                    not in retired_id_set
                )
            }

        return _ObservationPlan(
            visit_states=next_states,
            request_required=request_required,
        )

    def _commit_plan(self, plan: _ObservationPlan) -> None:
        self._visit_states = plan.visit_states
        if plan.request_required:
            self._request_pending = True

    def _freshness_recovered(
        self,
        *,
        previous: datetime | None,
        current: datetime | None,
    ) -> bool:
        if previous is None or current is None or current <= previous:
            return False

        return (
            current - previous
        ).total_seconds() > self._policy.monitoring_freshness_seconds

    @staticmethod
    def _latest_timestamp(
        previous: datetime | None,
        current: datetime | None,
    ) -> datetime | None:
        if current is None:
            return previous
        if previous is None or current > previous:
            return current
        return previous

    @staticmethod
    def _reliable_observed_at(
        visit: ZoneVisit,
    ) -> datetime | None:
        observation = visit.observation
        if observation.state is not ObservationState.OBSERVED:
            return None
        return observation.last_reliable_observed_at

    @staticmethod
    def _fingerprint(
        visit: ZoneVisit,
    ) -> _VisitSemanticFingerprint:
        return _VisitSemanticFingerprint(
            visit_id=visit.visit_id,
            physical_vehicle_id=visit.physical_vehicle_id,
            zone_id=visit.zone_id,
            state=visit.state,
            observation_state=visit.observation.state,
            observation_reason=visit.observation.reason,
        )


def compose_frame_observers(
    *observers: FrameObserver | None,
) -> FrameObserver | None:
    """None을 제외한 frame observer를 입력 순서대로 합성한다.

    Generic observer의 예외는 숨기지 않는다. ToF observer의 오류 격리는
    TofMonitoringContextObserver 자체의 책임이다.
    """

    active_observers: list[FrameObserver] = []

    for index, observer in enumerate(observers):
        if observer is None:
            continue
        if not callable(observer):
            raise TypeError(
                f"observers[{index}] must be callable or None"
            )
        active_observers.append(observer)

    if not active_observers:
        return None
    if len(active_observers) == 1:
        return active_observers[0]

    composed_observers = tuple(active_observers)

    def composed(
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        for observer in composed_observers:
            observer(frame, batch, result)

    return composed

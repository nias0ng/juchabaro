"""EntryMatchAttempt의 물리 차량 매칭 전이를 소유한다.

이 coordinator는 ENTRY_EXIT 구역 관측과 대기 시도를 결합해
``EntryMatchAttempt`` snapshot을 새로 만든다. snapshot을 저장하거나
HTTP DTO를 번역하는 책임은 가지지 않는다. 따라서 호출자는 반환된
전이를 같은 UnitOfWork에서 durable repository에 저장해야 한다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable, Mapping

from src.domain.models import ObservationState, ObservationStatus, require_aware
from src.parking.geometry import NormalizedPolygon as GeometryPolygon
from src.parking.geometry import overlap_ratio
from src.parking.models import EntryExitRole, ZoneType
from src.parking.zone_registry import ZoneRegistry
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    SessionContext,
)
from src.tracking.models import BoundingBox, PhysicalVehicleId


class EntryMatchTransitionError(RuntimeError):
    """요청한 EntryMatchAttempt 전이가 현재 snapshot과 충돌한다."""


class StaleEntryDecisionError(EntryMatchTransitionError):
    """현재보다 낮은 decisionRevision이 전달됐다."""


_REVIEW_RESOLUTIONS = frozenset(
    {
        EntryDecisionState.REVIEW_ALLOW,
        EntryDecisionState.REVIEW_DENY,
        EntryDecisionState.REVIEW_EXPIRED,
    }
)
_INITIAL_DECISIONS = frozenset(
    {
        EntryDecisionState.ALLOW,
        EntryDecisionState.DENY,
        EntryDecisionState.REVIEW_PENDING,
    }
)


class EntryMatchCoordinator:
    """Entry decision과 ENTRY_EXIT 관측을 독립 축으로 유지한다.

    인스턴스 안에 attempt나 idempotency key를 캐시하지 않는다. pending
    attempt 조회와 optimistic write는 repository의 책임이며, 이 class는
    어떤 immutable snapshot이 다음 상태인지만 결정한다.
    """

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        entry_zone_min_overlap_ratio: float = 0.40,
    ) -> None:
        if not 0.0 < entry_zone_min_overlap_ratio <= 1.0:
            raise ValueError(
                "entry_zone_min_overlap_ratio must be greater than 0 and at most 1"
            )
        self._entry_zones = tuple(
            zone
            for zone in zones.all()
            if zone.zone_type is ZoneType.ENTRY_EXIT
            and zone.entry_exit_role is EntryExitRole.ENTRY
        )
        self._entry_zone_min_overlap_ratio = entry_zone_min_overlap_ratio

    def open_attempt(
        self,
        *,
        entry_attempt_id: EntryAttemptId,
        decision_state: EntryDecisionState,
        decision_revision: int,
        created_at: datetime,
        match_deadline_at: datetime,
        authoritative_context: SessionContext | None = None,
    ) -> EntryMatchAttempt:
        """접수한 입차 decision을 PENDING 매칭 snapshot으로 만든다.

        ``created_at``은 upstream에서 입차 시도를 만든 시각이며 현재
        wire의 ``entryTime``에 해당한다. Jetson local 접수 시각은 durable
        input receipt가 별도로 소유한다. deadline은 직접 받으며 임의
        default를 두지 않는다. ALLOW계열의 session/context 필수 조건은
        ``EntryMatchAttempt`` 불변식이 검증한다.
        """

        require_aware(created_at, "created_at")
        require_aware(match_deadline_at, "match_deadline_at")
        if match_deadline_at < created_at:
            raise ValueError("match_deadline_at must not precede created_at")
        if decision_state not in _INITIAL_DECISIONS:
            raise EntryMatchTransitionError(
                "a review resolution requires an existing REVIEW_PENDING attempt"
            )

        return EntryMatchAttempt(
            entry_attempt_id=entry_attempt_id,
            match_state=EntryMatchState.PENDING,
            decision_state=decision_state,
            decision_revision=decision_revision,
            authoritative_session_id=(
                None
                if authoritative_context is None
                else authoritative_context.parking_session_id
            ),
            authoritative_context=authoritative_context,
            match_deadline_at=match_deadline_at,
            record_version=1,
            created_at=created_at,
            updated_at=created_at,
        )

    def apply_decision(
        self,
        attempt: EntryMatchAttempt,
        *,
        decision_state: EntryDecisionState,
        decision_revision: int,
        updated_at: datetime,
        authoritative_context: SessionContext | None = None,
    ) -> EntryMatchAttempt:
        """decision retry나 REVIEW 해소를 검증해 적용한다.

        같은 revision·같은 내용은 멱등 retry로 기존 snapshot을 반환한다.
        같은 revision의 다른 내용, settled decision의 변경, REVIEW_PENDING
        이외 상태의 higher revision은 conflict다.
        """

        require_aware(updated_at, "updated_at")
        authoritative_session_id = (
            None if authoritative_context is None else authoritative_context.parking_session_id
        )
        requested_identity = (
            decision_state,
            authoritative_session_id,
            authoritative_context,
        )
        current_identity = (
            attempt.decision_state,
            attempt.authoritative_session_id,
            attempt.authoritative_context,
        )

        if decision_revision < attempt.decision_revision:
            raise StaleEntryDecisionError(
                "decision_revision is older than the accepted EntryMatchAttempt"
            )
        if decision_revision == attempt.decision_revision:
            if requested_identity == current_identity:
                return attempt
            raise EntryMatchTransitionError(
                "the same decision_revision was reused with different content"
            )

        if updated_at < attempt.updated_at:
            raise ValueError("updated_at must not precede the current attempt update")

        if (
            attempt.decision_state is not EntryDecisionState.REVIEW_PENDING
            or decision_state not in _REVIEW_RESOLUTIONS
        ):
            raise EntryMatchTransitionError(
                "only REVIEW_PENDING may advance to a higher review resolution"
            )

        return replace(
            attempt,
            decision_state=decision_state,
            decision_revision=decision_revision,
            authoritative_session_id=authoritative_session_id,
            authoritative_context=authoritative_context,
            record_version=attempt.record_version + 1,
            updated_at=updated_at,
        )

    def match_earliest(
        self,
        attempts: Iterable[EntryMatchAttempt],
        *,
        observed_vehicle_bboxes: Mapping[PhysicalVehicleId, BoundingBox],
        observed_at: datetime,
    ) -> EntryMatchAttempt | None:
        """한 sample의 ENTRY 후보가 하나일 때만 가장 오래된 attempt를 매칭한다.

        EXIT 역할 구역과 입구 밖 차량은 후보가 아니다. 같은 sample의
        ENTRY 후보가 두 대 이상이면 detector 순서로 identity를 추측하지
        않고 모두 보류한다. 대기 순서는 in-memory 삽입 순서가 아니라
        ``created_at``이다. deadline을 지난 attempt는 고르지 않으며,
        호출자는 같은 frame transaction에서 ``expire_due()`` 결과도 저장해야
        한다.
        """

        require_aware(observed_at, "observed_at")
        entry_candidates = tuple(
            physical_vehicle_id
            for physical_vehicle_id, bbox in observed_vehicle_bboxes.items()
            if self._is_in_entry_zone(bbox)
        )
        if len(entry_candidates) != 1:
            return None
        physical_vehicle_id = entry_candidates[0]

        eligible = sorted(
            (
                attempt
                for attempt in attempts
                if attempt.match_state is EntryMatchState.PENDING
                and attempt.created_at <= observed_at
                and observed_at <= attempt.match_deadline_at
            ),
            key=lambda attempt: (attempt.created_at, str(attempt.entry_attempt_id)),
        )
        if not eligible:
            return None

        attempt = eligible[0]
        return replace(
            attempt,
            match_state=EntryMatchState.MATCHED,
            matched_physical_vehicle_id=physical_vehicle_id,
            match_terminated_at=observed_at,
            record_version=attempt.record_version + 1,
            updated_at=observed_at,
        )

    def expire_due(
        self,
        attempts: Iterable[EntryMatchAttempt],
        *,
        observed_at: datetime,
        observation: ObservationStatus,
    ) -> tuple[EntryMatchAttempt, ...]:
        """deadline을 지난 PENDING attempt를 명시적 EXPIRED로 만든다.

        전체 관측이 정상이 아니었다면 임의 차량에 매칭하지 않고
        ``SOURCE_UNAVAILABLE``로 남긴다. 이 사유는 physical departure를
        의미하지 않는다.
        """

        require_aware(observed_at, "observed_at")
        reason = (
            "MATCH_DEADLINE_EXCEEDED"
            if observation.state is ObservationState.OBSERVED
            else "SOURCE_UNAVAILABLE"
        )
        return tuple(
            self.terminate(
                attempt,
                state=EntryMatchState.EXPIRED,
                terminated_at=observed_at,
                reason=reason,
            )
            for attempt in attempts
            if attempt.match_state is EntryMatchState.PENDING
            and observed_at > attempt.match_deadline_at
        )

    def terminate(
        self,
        attempt: EntryMatchAttempt,
        *,
        state: EntryMatchState,
        terminated_at: datetime,
        reason: str,
    ) -> EntryMatchAttempt:
        """PENDING attempt을 EXPIRED·FAILED·CANCELED 중 하나로 종료한다."""

        require_aware(terminated_at, "terminated_at")
        if state not in {
            EntryMatchState.EXPIRED,
            EntryMatchState.FAILED,
            EntryMatchState.CANCELED,
        }:
            raise ValueError("terminate requires an unsuccessful terminal match state")
        if not reason:
            raise ValueError("terminal reason must not be empty")
        if terminated_at < attempt.updated_at:
            raise ValueError("terminated_at must not precede the current attempt update")

        if attempt.match_state is not EntryMatchState.PENDING:
            if attempt.match_state is state and attempt.terminal_reason == reason:
                return attempt
            raise EntryMatchTransitionError("a terminal match outcome cannot be changed")

        return replace(
            attempt,
            match_state=state,
            match_terminated_at=terminated_at,
            terminal_reason=reason,
            record_version=attempt.record_version + 1,
            updated_at=terminated_at,
        )

    def _is_in_entry_zone(self, bbox: BoundingBox) -> bool:
        # ZoneDefinition의 tuple polygon을 기존 순수 geometry value object로
        # 번역한다. 구역의 정본은 여전히 ZoneRegistry snapshot이다.
        return any(
            overlap_ratio(GeometryPolygon(tuple(zone.polygon)), bbox)
            >= self._entry_zone_min_overlap_ratio
            for zone in self._entry_zones
        )

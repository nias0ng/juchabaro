"""authoritative session context와 PhysicalVehicle 연결을 소유한다.

EntryMatchCoordinator가 물리 매칭을 만들어도 binding은 이 coordinator만
생성·갱신·종료한다. tracking snapshot에 session context를 복사하지
않고, 규칙 평가자는 active ContextBinding을 조회해 문맥을 얻는다.
ParkingSessionMirror presence 전이와 물리 출차 transaction은
PhysicalPresenceCoordinator의 책임으로 남긴다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable, Iterable
from uuid import UUID, uuid4

from src.domain.models import require_aware
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.tracking.models import PhysicalVehicle, PhysicalVehicleId, PhysicalVehicleState


class ContextBindingError(RuntimeError):
    """ContextBinding 생성 조건이 충족되지 않거나 기존 identity와 충돌한다."""


class StaleContextRevisionError(ContextBindingError):
    """현재 binding보다 낮은 contextRevision이 전달됐다."""


class ContextBindingCoordinator:
    """ContextBinding의 immutable identity와 active cardinality를 검증한다.

    DB unique index가 동시 write의 최종 방어선이다. 이 coordinator의
    ``existing_bindings`` 검사는 domain conflict를 SQLite 오류보다 먼저
    분류하기 위한 전이 규칙이다.
    """

    def __init__(self, *, id_factory: Callable[[], UUID] = uuid4) -> None:
        self._id_factory = id_factory

    def bind(
        self,
        *,
        attempt: EntryMatchAttempt,
        physical_vehicle: PhysicalVehicle,
        session_mirror: ParkingSessionMirror,
        existing_bindings: Iterable[ContextBinding],
        bound_at: datetime,
    ) -> ContextBinding:
        """MATCHED+ALLOW attempt를 active vehicle·session에 한 번만 binding한다."""

        require_aware(bound_at, "bound_at")
        if attempt.match_state is not EntryMatchState.MATCHED:
            raise ContextBindingError("ContextBinding requires a MATCHED entry attempt")
        if attempt.decision_state not in {
            EntryDecisionState.ALLOW,
            EntryDecisionState.REVIEW_ALLOW,
        }:
            raise ContextBindingError("ContextBinding requires ALLOW or REVIEW_ALLOW")
        if attempt.authoritative_session_id is None or attempt.authoritative_context is None:
            raise ContextBindingError("ContextBinding requires authoritative session context")
        if attempt.matched_physical_vehicle_id != physical_vehicle.physical_vehicle_id:
            raise ContextBindingError("attempt and PhysicalVehicle identity do not match")
        if physical_vehicle.state is not PhysicalVehicleState.ACTIVE:
            raise ContextBindingError("only an ACTIVE PhysicalVehicle may be bound")

        if session_mirror.parking_session_id != attempt.authoritative_session_id:
            raise ContextBindingError("attempt and ParkingSessionMirror identity do not match")
        if session_mirror.administrative_state is not SessionAdministrativeState.ACTIVE:
            raise ContextBindingError("an administratively closed session cannot be bound")
        if session_mirror.physical_presence_state is PhysicalPresenceState.EXITED:
            raise ContextBindingError("an already exited session cannot be bound")
        if not session_mirror.exit_correlation_enabled:
            raise ContextBindingError("a conflict-disabled session correlation cannot be bound")
        if session_mirror.physical_vehicle_id not in {
            None,
            physical_vehicle.physical_vehicle_id,
        }:
            raise ContextBindingError("session mirror is correlated with another PhysicalVehicle")

        # EntryMatchAttempt는 입차 당시 context snapshot이다. 이후 Backend가
        # 더 높은 revision을 반영한 mirror가 있다면 그 최신 context가 binding의
        # 정본이며, 오래된 attempt 값으로 되돌리지 않는다.
        binding_context = session_mirror.last_context
        if binding_context is None:
            binding_context = attempt.authoritative_context
        if binding_context.parking_session_id != session_mirror.parking_session_id:
            raise ContextBindingError(
                "binding context and ParkingSessionMirror identity do not match"
            )
        context_revision = session_mirror.context_revision

        known_bindings = tuple(existing_bindings)
        for existing in known_bindings:
            if existing.entry_attempt_id == attempt.entry_attempt_id:
                if (
                    existing.state is ContextBindingState.BOUND
                    and existing.parking_session_id == attempt.authoritative_session_id
                    and existing.physical_vehicle_id == physical_vehicle.physical_vehicle_id
                    and existing.context == binding_context
                    and existing.context_revision == context_revision
                ):
                    return existing
                raise ContextBindingError("entryAttemptId already owns an immutable binding")

        for existing in known_bindings:
            if existing.state is not ContextBindingState.BOUND:
                continue
            if existing.parking_session_id == attempt.authoritative_session_id:
                raise ContextBindingError("session already has an active ContextBinding")
            if existing.physical_vehicle_id == physical_vehicle.physical_vehicle_id:
                raise ContextBindingError(
                    "PhysicalVehicle already has an active authoritative ContextBinding"
                )

        return ContextBinding(
            context_binding_id=ContextBindingId(self._id_factory()),
            entry_attempt_id=attempt.entry_attempt_id,
            parking_session_id=attempt.authoritative_session_id,
            physical_vehicle_id=physical_vehicle.physical_vehicle_id,
            state=ContextBindingState.BOUND,
            context_revision=context_revision,
            context=binding_context,
            record_version=1,
            bound_at=bound_at,
            updated_at=bound_at,
        )

    def update_context(
        self,
        binding: ContextBinding,
        *,
        context: SessionContext,
        context_revision: int,
        updated_at: datetime,
    ) -> ContextBinding:
        """같은 binding identity의 자격 context만 higher revision으로 갱신한다."""

        require_aware(updated_at, "updated_at")
        if context.parking_session_id != binding.parking_session_id:
            raise ContextBindingError("context update cannot change parkingSessionId")
        if context_revision < binding.context_revision:
            raise StaleContextRevisionError(
                "context_revision is older than the active ContextBinding"
            )
        if context_revision == binding.context_revision:
            if context == binding.context:
                return binding
            raise ContextBindingError(
                "the same context_revision was reused with different content"
            )
        if updated_at < binding.updated_at:
            raise ValueError("updated_at must not precede the current binding update")
        if binding.state is not ContextBindingState.BOUND:
            raise ContextBindingError("an ended ContextBinding cannot accept context updates")

        return replace(
            binding,
            context_revision=context_revision,
            context=context,
            record_version=binding.record_version + 1,
            updated_at=updated_at,
        )

    def end(
        self,
        binding: ContextBinding,
        *,
        ended_at: datetime,
        reason: str,
    ) -> ContextBinding:
        """binding을 EXIT·ADMIN_CLOSED·정정으로 종료하되 차량은 유지한다."""

        require_aware(ended_at, "ended_at")
        if not reason:
            raise ValueError("termination reason must not be empty")
        if ended_at < binding.updated_at:
            raise ValueError("ended_at must not precede the current binding update")
        if binding.state is ContextBindingState.ENDED:
            if binding.termination_reason == reason:
                return binding
            raise ContextBindingError("an ended ContextBinding cannot change its reason")

        return replace(
            binding,
            state=ContextBindingState.ENDED,
            ended_at=ended_at,
            termination_reason=reason,
            record_version=binding.record_version + 1,
            updated_at=ended_at,
        )

    def active_binding_for(
        self,
        bindings: Iterable[ContextBinding],
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ContextBinding | None:
        """PhysicalVehicle의 authoritative active binding을 최대 하나 반환한다."""

        matched = tuple(
            binding
            for binding in bindings
            if binding.state is ContextBindingState.BOUND
            and binding.physical_vehicle_id == physical_vehicle_id
        )
        if len(matched) > 1:
            raise ContextBindingError(
                "multiple active ContextBindings violate PhysicalVehicle cardinality"
            )
        return matched[0] if matched else None

    def active_context_for(
        self,
        bindings: Iterable[ContextBinding],
        physical_vehicle_id: PhysicalVehicleId,
    ) -> SessionContext | None:
        """tracking snapshot이 아닌 active binding에서 규칙 문맥을 조회한다."""

        binding = self.active_binding_for(bindings, physical_vehicle_id)
        return None if binding is None else binding.context

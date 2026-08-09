"""API 5 SessionContextUpdate를 session mirror와 binding에 반영한다.

Backend 행정 상태와 authoritative 자격 문맥만 갱신한다. ``CLOSED``는 active
ContextBinding을 끝내지만 PhysicalVehicle과 현장 presence, 주차·Incident
aggregate를 출차 상태로 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime

from src.communication.models import (
    InboundApplicationResult,
    SessionContextUpdateInput,
)
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.models import (
    ContextBinding,
    ContextBindingState,
    EntryAttemptId,
    ParkingSessionMirror,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.codecs import datetime_from_epoch_microseconds
from src.storage.repositories import (
    AcceptanceResult,
    AcceptedInputRepository,
    ContextBindingRepository,
    ParkingSessionMirrorRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import ParkingSessionId, VehicleId


_ACCEPTED_INPUT_TYPE = "SessionContextUpdate"
_LOGGER = logging.getLogger(__name__)

AfterAppliedCallback = Callable[[], None]


class SessionContextUpdateNotFoundError(LookupError):
    """갱신할 ParkingSessionMirror가 Jetson durable state에 없다."""


class SessionContextUpdateConflictError(RuntimeError):
    """session identity, revision 또는 행정 상태 전이가 기존 값과 충돌한다."""


@dataclass(frozen=True, kw_only=True)
class SessionContextUpdateAcceptance:
    """API 5 durable acceptance 응답에 필요한 값."""

    session_id: ParkingSessionId
    context_revision: int
    application_result: InboundApplicationResult
    accepted_at: datetime


class SessionContextUpdateIntake:
    """Session context와 active binding lifecycle을 원자적으로 갱신한다.

    ``after_applied``는 새 입력의 durable transaction이 commit된 뒤
    ``APPLIED`` 결과에서만 호출되는 best-effort 신호다. callback은
    가볍고 non-blocking이어야 하며 DB 조회나 후속 business logic을
    직접 실행하지 않아야 한다. callback 실패는 로깅하되 이미 확정된
    durable acceptance에는 전파하지 않는다.
    """

    def __init__(
        self,
        coordinator: ContextBindingCoordinator,
        *,
        after_applied: AfterAppliedCallback | None = None,
    ) -> None:
        if after_applied is not None and not callable(after_applied):
            raise TypeError("after_applied must be callable or None")

        self._coordinator = coordinator
        self._after_applied = after_applied

    def receive(
        self,
        update: SessionContextUpdateInput,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
    ) -> SessionContextUpdateAcceptance:
        """동일 domain input retry는 상태를 재적용하지 않는다."""

        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

        session_id = ParkingSessionId(update.session_id)
        entry_attempt_id = EntryAttemptId(update.entry_attempt_id)
        request_payload = _canonical_request_payload(update)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        binding_repository = ContextBindingRepository(connection)

        with UnitOfWork(connection):
            mirror = mirror_repository.get(session_id)
            if mirror is None:
                raise SessionContextUpdateNotFoundError(
                    f"ParkingSessionMirror를 찾을 수 없습니다: {session_id}"
                )
            if mirror.entry_attempt_id != entry_attempt_id:
                raise SessionContextUpdateConflictError(
                    "entryAttemptId가 기존 session correlation과 다릅니다."
                )

            is_stale = update.context_revision < mirror.context_revision
            acceptance = AcceptedInputRepository(connection).accept(
                input_type=_ACCEPTED_INPUT_TYPE,
                input_identity=str(int(session_id)),
                input_revision=update.context_revision,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                workflow_state=(
                    "SESSION_CONTEXT_STALE"
                    if is_stale
                    else "SESSION_CONTEXT_UPDATED"
                ),
            )
            if acceptance.created and not is_stale:
                next_mirror = _apply_mirror_update(mirror, update)
                binding = binding_repository.get_by_entry_attempt_id(
                    entry_attempt_id
                )
                if binding is not None:
                    if binding.parking_session_id != session_id:
                        raise SessionContextUpdateConflictError(
                            "ContextBinding과 session identity가 다릅니다."
                        )
                    if binding.state is ContextBindingState.BOUND:
                        self._update_active_binding(
                            binding,
                            context=next_mirror.last_context,
                            context_revision=update.context_revision,
                            administrative_state=(
                                next_mirror.administrative_state
                            ),
                            updated_at=update.updated_at,
                            repository=binding_repository,
                        )

                if next_mirror.record_version != mirror.record_version:
                    mirror_repository.save(
                        next_mirror,
                        expected_record_version=mirror.record_version,
                    )

        result = SessionContextUpdateAcceptance(
            session_id=session_id,
            context_revision=update.context_revision,
            application_result=_application_result(acceptance),
            accepted_at=datetime_from_epoch_microseconds(
                acceptance.record.accepted_at_us
            ),
        )

        if result.application_result is InboundApplicationResult.APPLIED:
            self._notify_after_applied(session_id)

        return result

    def _notify_after_applied(
        self,
        session_id: ParkingSessionId,
    ) -> None:
        callback = self._after_applied
        if callback is None:
            return

        try:
            callback()
        except Exception:
            _LOGGER.exception(
                "SessionContextUpdate post-commit callback failed "
                "stage=post_commit_reevaluation_signal "
                "applicationResult=APPLIED "
                "sessionId=%s",
                session_id,
            )

    def _update_active_binding(
        self,
        binding: ContextBinding,
        *,
        context: SessionContext | None,
        context_revision: int,
        administrative_state: SessionAdministrativeState,
        updated_at: datetime,
        repository: ContextBindingRepository,
    ) -> ContextBinding:
        if context is None:  # ParkingSessionMirror invariant 방어.
            raise SessionContextUpdateConflictError(
                "active ContextBinding update requires session context"
            )

        current_version = binding.record_version
        updated_binding = self._coordinator.update_context(
            binding,
            context=context,
            context_revision=context_revision,
            updated_at=updated_at,
        )
        if updated_binding.record_version != current_version:
            repository.save(
                updated_binding,
                expected_record_version=current_version,
            )
            current_version = updated_binding.record_version

        if administrative_state is SessionAdministrativeState.CLOSED:
            ended_binding = self._coordinator.end(
                updated_binding,
                ended_at=updated_at,
                reason="ADMIN_CLOSED",
            )
            if ended_binding.record_version != current_version:
                repository.save(
                    ended_binding,
                    expected_record_version=current_version,
                )
            return ended_binding
        return updated_binding


def _apply_mirror_update(
    mirror: ParkingSessionMirror,
    update: SessionContextUpdateInput,
) -> ParkingSessionMirror:
    administrative_state = SessionAdministrativeState(
        update.administrative_state
    )
    context = SessionContext(
        parking_session_id=mirror.parking_session_id,
        vehicle_id=VehicleId(update.session_context.vehicle_id),
        is_disabled_vehicle=update.session_context.is_disabled_vehicle,
        is_electric=update.session_context.is_electric,
    )

    if update.context_revision < mirror.context_revision:
        raise SessionContextUpdateConflictError(
            "contextRevision이 현재 session mirror보다 낮습니다."
        )
    if update.context_revision == mirror.context_revision:
        if (
            administrative_state is mirror.administrative_state
            and context == mirror.last_context
            and update.updated_at == mirror.updated_at
        ):
            return mirror
        raise SessionContextUpdateConflictError(
            "같은 contextRevision이 다른 내용으로 재사용되었습니다."
        )
    if (
        mirror.administrative_state is SessionAdministrativeState.CLOSED
        and administrative_state is SessionAdministrativeState.ACTIVE
    ):
        raise SessionContextUpdateConflictError(
            "CLOSED session은 ACTIVE로 되돌릴 수 없습니다."
        )
    if update.updated_at < mirror.updated_at:
        raise SessionContextUpdateConflictError(
            "updatedAt이 현재 session mirror 갱신 시각보다 이전입니다."
        )

    return replace(
        mirror,
        administrative_state=administrative_state,
        context_revision=update.context_revision,
        last_context=context,
        record_version=mirror.record_version + 1,
        updated_at=update.updated_at,
    )


def _application_result(
    acceptance: AcceptanceResult,
) -> InboundApplicationResult:
    if acceptance.record.workflow_state == "SESSION_CONTEXT_STALE":
        return InboundApplicationResult.STALE
    if not acceptance.created:
        return InboundApplicationResult.ALREADY_APPLIED
    return InboundApplicationResult.APPLIED


def _canonical_request_payload(update: SessionContextUpdateInput) -> bytes:
    return json.dumps(
        {
            "administrativeState": update.administrative_state,
            "contextRevision": update.context_revision,
            "entryAttemptId": str(update.entry_attempt_id),
            "sessionContext": {
                "isDisabledVehicle": (
                    update.session_context.is_disabled_vehicle
                ),
                "isElectric": update.session_context.is_electric,
                "vehicleId": update.session_context.vehicle_id,
            },
            "sessionId": update.session_id,
            "updatedAt": update.updated_at.isoformat(timespec="microseconds"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

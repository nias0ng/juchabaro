"""구역 방문 상태축의 구현 계약.

상태는 OUTSIDE → ENTERING → INSIDE → EXITING 순으로 전이한다. PRESENT와
ABSENT의 진입·이탈 확인시간은 구현체가 누적하고, UNKNOWN은 시간을 누적하거나
기존 상태를 즉시 초기화하지 않는다. 한 차량은 여러 구역을 동시에 방문할 수
있으므로 상태는 (physical_vehicle_id, zone_id)별로 독립 관리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from src.parking.models import (
    PresenceSignal,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import PhysicalVehicleId


class ZoneVisitTracker(Protocol):
    """구역 존재 신호를 연속적인 ZoneVisit 상태로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """현재 방문을 반환하고 활성 방문이 없으면 None을 반환한다."""

        ...


@dataclass
class _VisitSlot:
    """(차량, 구역) 한 쌍의 가변 상태. 외부에는 frozen ZoneVisit만 내보낸다.

    `accumulated_seconds`는 현재 전이(진입 확인 또는 이탈 확인)를 향해 **관측된**
    시간의 합이다. 벽시계 경과가 아니다. `last_observed_at`이 `None`이면 직전에
    UNKNOWN을 만나 누적 사슬이 끊긴 상태이며, 다음 관측은 간격 0을 기여한다.

    `last_updated_at`은 신호 종류와 무관하게 `update()`가 마지막으로 이 슬롯을
    건드린 시각이다. UNKNOWN에 끊기는 `last_observed_at`과 달리 항상 채워져 있어
    관측 순서 검사의 기준이 된다.
    """

    visit: ZoneVisit
    last_updated_at: datetime
    accumulated_seconds: float = 0.0
    last_observed_at: datetime | None = None
    closed_reported: bool = False

    def accumulate(self, observed_at: datetime) -> float:
        """직전 관측과의 간격을 누적하고 누적값을 반환한다.

        사슬이 끊겼으면(UNKNOWN 직후) 간격을 더하지 않고 사슬만 다시 잇는다.
        """

        if self.last_observed_at is not None:
            self.accumulated_seconds += (observed_at - self.last_observed_at).total_seconds()
        self.last_observed_at = observed_at
        return self.accumulated_seconds

    def restart(self, observed_at: datetime | None) -> None:
        """누적을 0으로 되돌린다. 상태 전이가 일어난 직후에 부른다."""

        self.accumulated_seconds = 0.0
        self.last_observed_at = observed_at

    def break_chain(self) -> None:
        """누적 사슬만 끊는다. 이미 쌓인 값은 보존한다 (UNKNOWN 처리)."""

        self.last_observed_at = None


class InMemoryZoneVisitTracker:
    """구역 존재 신호를 연속적인 ZoneVisit 상태로 변환한다.

    상태는 (physical_vehicle_id, zone_id)별로 독립이다. 한 차량이 여러 구역에
    동시에 INSIDE일 수 있고, 한 구역에 여러 차량이 동시에 INSIDE일 수 있다.

    UNKNOWN은 시간을 누적하지도, 기존 상태를 초기화하지도 않는다 — 관측이
    끊긴 구간을 진입·이탈 확인시간에 넣으면 카메라 장애가 판정을 바꾼다.
    """

    def __init__(self, *, entry_confirm_seconds: float, exit_confirm_seconds: float) -> None:
        if entry_confirm_seconds < 0 or exit_confirm_seconds < 0:
            raise ValueError("확인시간은 음수일 수 없습니다.")
        self._entry_confirm_seconds = entry_confirm_seconds
        self._exit_confirm_seconds = exit_confirm_seconds
        self._slots: dict[tuple[PhysicalVehicleId, ZoneId], _VisitSlot] = {}

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """현재 방문을 반환한다. 활성 방문이 없으면 None을 반환한다.

        방문이 닫히는 프레임에서는 `exited_at`이 채워진 방문을 한 번 반환한다 —
        규칙이 `matched=false`를 만들어 RESOLVE를 일으키려면 종료를 봐야 한다.
        그 다음 프레임부터는 None이다.

        `observed_at`은 timezone-aware여야 하고 같은 (차량, 구역) 쌍의 직전
        관측보다 과거일 수 없다. 위반하면 ValueError다(`time_guard` 참조).
        """

        key = (physical_vehicle_id, zone_id)
        slot = self._slots.get(key)
        # 뒤로 간 관측을 그대로 받으면 accumulate()가 음수를 더해 진입·이탈 확정이
        # 조용히 늦어진다. 상태가 (차량, 구역)별로 독립이므로 순서도 쌍별로 본다 —
        # 한 프레임 안에서 쌍들을 어떤 순서로 갱신하든 무관해야 하기 때문이다.
        ensure_forward_observation(
            observed_at, None if slot is None else slot.last_updated_at
        )
        if slot is not None:
            slot.last_updated_at = observed_at

        if signal is PresenceSignal.UNKNOWN:
            # 시간을 누적하지 않고 상태도 바꾸지 않는다. 이미 쌓인 누적은
            # 보존하고 사슬만 끊는다.
            if slot is None or slot.closed_reported:
                return None
            slot.break_chain()
            return slot.visit

        if slot is None:
            if signal is PresenceSignal.ABSENT:
                return None
            return self._open_candidate(key, physical_vehicle_id, zone_id, observed_at)

        if slot.closed_reported:
            # 종료를 이미 알린 슬롯이다. PRESENT면 새 방문을 시작한다.
            if signal is PresenceSignal.ABSENT:
                return None
            return self._open_candidate(key, physical_vehicle_id, zone_id, observed_at)

        visit = slot.visit
        if visit.state is ZoneVisitState.ENTERING:
            return self._advance_entering(slot, signal, observed_at)
        if visit.state is ZoneVisitState.INSIDE:
            return self._advance_inside(slot, signal, observed_at)
        if visit.state is ZoneVisitState.EXITING:
            return self._advance_exiting(slot, signal, observed_at)
        return visit

    def active_visits(self, physical_vehicle_id: PhysicalVehicleId) -> tuple[ZoneVisit, ...]:
        """이 차량의 INSIDE 방문만 반환한다. 규칙 평가의 입력이다."""

        return tuple(
            slot.visit
            for (vehicle_id, _zone_id), slot in self._slots.items()
            if vehicle_id == physical_vehicle_id
            and not slot.closed_reported
            and slot.visit.state is ZoneVisitState.INSIDE
        )

    def _open_candidate(
        self,
        key: tuple[PhysicalVehicleId, ZoneId],
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        observed_at: datetime,
    ) -> ZoneVisit:
        visit = ZoneVisit(
            visit_id=self._make_visit_id(physical_vehicle_id, zone_id, observed_at),
            physical_vehicle_id=physical_vehicle_id,
            zone_id=zone_id,
            state=ZoneVisitState.ENTERING,
            entered_candidate_at=observed_at,
        )
        slot = _VisitSlot(
            visit=visit, last_updated_at=observed_at, last_observed_at=observed_at
        )
        self._slots[key] = slot
        # 확인시간이 0이면 첫 관측으로 즉시 확정한다.
        if self._entry_confirm_seconds <= 0.0:
            slot.visit = replace(visit, state=ZoneVisitState.INSIDE, entered_at=observed_at)
            slot.restart(observed_at)
        return slot.visit

    def _advance_entering(
        self, slot: _VisitSlot, signal: PresenceSignal, observed_at: datetime
    ) -> ZoneVisit | None:
        if signal is PresenceSignal.ABSENT:
            # 진입 확인 전에 사라졌다. 후보를 버린다 — 방문이 성립하지 않았으므로
            # 닫힌 방문으로 보고하지 않는다.
            del self._slots[(slot.visit.physical_vehicle_id, slot.visit.zone_id)]
            return None

        if slot.accumulate(observed_at) >= self._entry_confirm_seconds:
            slot.visit = replace(
                slot.visit,
                state=ZoneVisitState.INSIDE,
                # 점유 시간의 기준이므로 확인 시각이 아니라 실제 진입 시점을 쓴다.
                entered_at=slot.visit.entered_candidate_at,
            )
            slot.restart(observed_at)
        return slot.visit

    def _advance_inside(
        self, slot: _VisitSlot, signal: PresenceSignal, observed_at: datetime
    ) -> ZoneVisit:
        if signal is PresenceSignal.PRESENT:
            # INSIDE에서는 누적할 전이가 없다. 사슬만 이어 둔다.
            slot.last_observed_at = observed_at
            return slot.visit

        slot.visit = replace(
            slot.visit, state=ZoneVisitState.EXITING, exit_candidate_at=observed_at
        )
        slot.restart(observed_at)
        if self._exit_confirm_seconds <= 0.0:
            slot.visit = replace(
                slot.visit, state=ZoneVisitState.OUTSIDE, exited_at=observed_at
            )
            slot.closed_reported = True
        return slot.visit

    def _advance_exiting(
        self, slot: _VisitSlot, signal: PresenceSignal, observed_at: datetime
    ) -> ZoneVisit:
        if signal is PresenceSignal.PRESENT:
            slot.visit = replace(
                slot.visit, state=ZoneVisitState.INSIDE, exit_candidate_at=None
            )
            slot.restart(observed_at)
            return slot.visit

        if slot.accumulate(observed_at) >= self._exit_confirm_seconds:
            slot.visit = replace(
                slot.visit,
                state=ZoneVisitState.OUTSIDE,
                # 실제로 사라진 시점을 종료 시각으로 쓴다. 확인시간은 판정 지연이지
                # 점유의 일부가 아니다.
                exited_at=slot.visit.exit_candidate_at,
            )
            slot.closed_reported = True
        return slot.visit

    @staticmethod
    def _make_visit_id(
        physical_vehicle_id: PhysicalVehicleId, zone_id: ZoneId, entered_candidate_at: datetime
    ) -> ZoneVisitId:
        """결정론적 방문 ID. uuid4를 쓰면 같은 입력의 두 실행이 달라져 리플레이
        검증이 불가능해진다."""

        return ZoneVisitId(f"{physical_vehicle_id}:{zone_id}:{entered_candidate_at.isoformat()}")

"""구역 방문 상태축의 구현 계약.

상태는 OUTSIDE → ENTERING → INSIDE → EXITING 순으로 전이한다. PRESENT와
ABSENT의 진입·이탈 확인시간은 구현체가 누적하고, UNKNOWN은 시간을 누적하거나
기존 상태를 즉시 초기화하지 않는다. 한 차량은 여러 구역을 동시에 방문할 수
있으므로 상태는 (physical_vehicle_id, zone_id)별로 독립 관리한다.

**프레임 호출 순서(조립기 계약).** 트래커에는 프레임 경계가 없다. 조립기가
프레임마다 아래 순서를 지켜야 방문 종료가 규칙에 정확히 한 번 보인다.

1. 이번 프레임에 관측된 (차량, 구역) 쌍마다 `update()`
2. 차량마다 `active_visits()` → 규칙 평가 → `IncidentReducer`
3. 프레임 끝에 `prune(now)` 한 번

3번을 빠뜨리면 종료 슬롯이 남아 같은 종료가 여러 프레임에 걸쳐 규칙에 보이고
(사건 상태는 축약기가 막아 주지만) 슬롯이 무한히 쌓인다.
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

    def active_visits(self, physical_vehicle_id: PhysicalVehicleId) -> tuple[ZoneVisit, ...]:
        """규칙 평가에 넘길 방문을 반환한다. 판정 중인 방문과 방금 닫힌 방문이다."""

        ...

    def prune(self, now: datetime) -> None:
        """프레임 판정이 끝난 뒤 종료 슬롯을 정리한다. 조립기가 매 프레임 부른다."""

        ...


# `active_visits()`가 규칙에 내보내는 상태. INSIDE는 "위반이 성립 중"이고,
# OUTSIDE는 "방금 닫혔다"이다. ENTERING/EXITING은 성립도 해소도 아직 결정되지
# 않았으므로 규칙에 보이지 않는다.
_JUDGED_STATES = frozenset({ZoneVisitState.INSIDE, ZoneVisitState.OUTSIDE})

# 조립기가 이 시간 동안 한 번도 `update()`를 주지 않은 열린 슬롯은 `prune()`이
# 강제 종료한다. 정상 경로(사라진 차량에 ABSENT를 계속 먹이기)가 끊겼을 때만
# 걸리는 안전망이므로 이탈 확인시간보다 훨씬 길게 잡는다.
DEFAULT_STALE_AFTER_SECONDS = 300.0


@dataclass
class _VisitSlot:
    """(차량, 구역) 한 쌍의 가변 상태. 외부에는 frozen ZoneVisit만 내보낸다.

    `accumulated_seconds`는 현재 전이(진입 확인 또는 이탈 확인)를 향해 **관측된**
    시간의 합이다. 벽시계 경과가 아니다. `last_observed_at`이 `None`이면 직전에
    UNKNOWN을 만나 누적 사슬이 끊긴 상태이며, 다음 관측은 간격 0을 기여한다.

    `last_updated_at`은 신호 종류와 무관하게 `update()`가 마지막으로 이 슬롯을
    건드린 시각이다. UNKNOWN에 끊기는 `last_observed_at`과 달리 항상 채워져 있어
    관측 순서 검사와 유휴 판정의 기준이 된다.

    닫힌 슬롯은 `visit.state`가 `OUTSIDE`인 슬롯이다. 별도 플래그를 두지 않는다 —
    상태와 플래그 두 곳에 같은 사실을 적으면 어긋날 자리가 생긴다.
    """

    visit: ZoneVisit
    last_updated_at: datetime
    accumulated_seconds: float = 0.0
    last_observed_at: datetime | None = None

    @property
    def is_closed(self) -> bool:
        """방문이 닫혔는가. 아직 판정에 전달되기 전이거나 정리 대기 중이다."""

        return self.visit.state is ZoneVisitState.OUTSIDE

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

    def __init__(
        self,
        *,
        entry_confirm_seconds: float,
        exit_confirm_seconds: float,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        if entry_confirm_seconds < 0 or exit_confirm_seconds < 0:
            raise ValueError("확인시간은 음수일 수 없습니다.")
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds는 음수일 수 없습니다.")
        self._entry_confirm_seconds = entry_confirm_seconds
        self._exit_confirm_seconds = exit_confirm_seconds
        self._stale_after_seconds = stale_after_seconds
        self._slots: dict[tuple[PhysicalVehicleId, ZoneId], _VisitSlot] = {}

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """이 (차량, 구역) 쌍의 현재 방문을 반환한다. 없으면 None을 반환한다.

        방문이 닫히는 프레임에서는 `exited_at`이 채워진 방문을 반환한다. **같은
        프레임의 `active_visits()`도 그 방문을 함께 내보내고**, 규칙은 그것을 보고
        `matched=False`를 만들어 `IncidentReducer`의 RESOLVE를 연다. 종료 슬롯은
        프레임 끝의 `prune()`이 지우므로 종료는 규칙에 정확히 한 번 보인다.

        조립기가 `prune()`을 빠뜨려도 이 쌍에 ABSENT나 UNKNOWN이 한 번 더 오면
        여기서 종료 슬롯을 지운다. 그때부터 반환값은 None이다.

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

        if slot is not None and slot.is_closed:
            # 종료 슬롯이다. 종료는 닫힌 프레임의 판정이 이미 봤으므로 여기서
            # 지운다 — 이 시점부터 슬롯이 없는 것과 완전히 같게 동작한다.
            del self._slots[key]
            if signal is PresenceSignal.PRESENT:
                return self._open_candidate(key, physical_vehicle_id, zone_id, observed_at)
            return None

        if signal is PresenceSignal.UNKNOWN:
            # 시간을 누적하지 않고 상태도 바꾸지 않는다. 이미 쌓인 누적은
            # 보존하고 사슬만 끊는다.
            if slot is None:
                return None
            slot.break_chain()
            return slot.visit

        if slot is None:
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
        """이 차량의 판정 대상 방문을 반환한다. 규칙 평가의 입력이다.

        `INSIDE`인 방문과 **이번 프레임에 닫힌 방문**(`OUTSIDE`, `exited_at`
        채워짐)을 함께 내보낸다. 닫힌 방문을 빼면 규칙이 `matched=False`를 만들
        기회가 없어 이미 열린 사건이 영원히 EDGE_CONFIRMED로 남고, 재진입은
        새 zone_visit_id로 두 번째 OPEN을 만들어 미해소 사건이 계속 쌓인다.

        `ENTERING`/`EXITING`은 제외한다. 진입 확인 전이거나 이탈 확인 중인 방문은
        위반 성립도 해소도 아직 결정되지 않았다.

        읽기 전용이다. 같은 프레임에서 몇 번을 불러도 같은 답을 준다 — "종료를
        정확히 한 번" 보장은 이 메서드가 아니라 프레임 끝의 `prune()`이 만든다.
        """

        return tuple(
            slot.visit
            for (vehicle_id, _zone_id), slot in self._slots.items()
            if vehicle_id == physical_vehicle_id and slot.visit.state in _JUDGED_STATES
        )

    def prune(self, now: datetime) -> None:
        """프레임 판정이 끝난 뒤 슬롯을 정리한다. **조립기가 매 프레임 한 번 부른다.**

        두 가지를 한다.

        1. 닫힌 슬롯을 지운다. 방금 끝난 프레임의 `active_visits()`가 종료를
           판정에 전달했으므로 역할이 끝났다. 종료가 규칙에 정확히 한 번 보이게
           만드는 장치가 바로 이 호출이다.
        2. `stale_after_seconds` 동안 `update()`가 한 번도 오지 않은 열린 슬롯을
           강제 종료한다. 트래커에는 프레임 경계가 없어 차량이 영영 돌아오지
           않는다는 사실을 스스로 알 수 없다 — 조립기가 그 쌍에 대한 `update()`를
           아예 멈추면(추적 소실 등) 슬롯이 무한히 남고, 그 차량의 열린 사건도
           영원히 닫히지 않는다.

        강제 종료된 방문은 조용히 사라지지 않고 다음 프레임의 `active_visits()`에
        한 번 실려 RESOLVE를 만든 뒤 그 다음 `prune()`에서 지워진다. 순서가
        중요하다 — 1번을 2번보다 먼저 해야 방금 강제 종료한 슬롯이 같은 호출에서
        판정 없이 지워지지 않는다.

        정상 경로는 조립기가 사라진 차량에 ABSENT를 계속 먹여 이탈 확인시간으로
        닫는 것이다. 강제 종료는 그 경로가 끊겼을 때만 걸리는 안전망이다.
        """

        ensure_forward_observation(now)

        for key in [key for key, slot in self._slots.items() if slot.is_closed]:
            del self._slots[key]

        if self._stale_after_seconds <= 0.0:
            return
        for key, slot in list(self._slots.items()):
            if (now - slot.last_updated_at).total_seconds() < self._stale_after_seconds:
                continue
            self._force_close(key, slot)

    def _force_close(
        self, key: tuple[PhysicalVehicleId, ZoneId], slot: _VisitSlot
    ) -> None:
        if slot.visit.state is ZoneVisitState.ENTERING:
            # 진입이 확정된 적 없는 후보다. 방문이 성립하지 않았으므로 종료로
            # 보고하지 않는다 — ABSENT로 후보를 버릴 때와 같은 처리다.
            del self._slots[key]
            return
        slot.visit = replace(
            slot.visit,
            state=ZoneVisitState.OUTSIDE,
            # 관측이 끊긴 시점까지만 점유로 인정한다. 관측하지 못한 구간을 점유에
            # 넣으면 EV 장기점유가 부풀려진다.
            exited_at=slot.visit.exit_candidate_at or slot.last_updated_at,
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
        return slot.visit

    @staticmethod
    def _make_visit_id(
        physical_vehicle_id: PhysicalVehicleId, zone_id: ZoneId, entered_candidate_at: datetime
    ) -> ZoneVisitId:
        """결정론적 방문 ID. uuid4를 쓰면 같은 입력의 두 실행이 달라져 리플레이
        검증이 불가능해진다."""

        return ZoneVisitId(f"{physical_vehicle_id}:{zone_id}:{entered_candidate_at.isoformat()}")

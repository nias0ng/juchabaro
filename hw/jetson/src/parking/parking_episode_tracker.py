"""10분 연속 정지 정책을 담당하는 주차 에피소드 상태축의 구현 계약.

STATIONARY 관측만 정지 시간에 누적하고 기본 600초에 도달하면 PARKED가 된다.
누적은 **관측된 시간**의 합이며 벽시계 경과가 아니다 — 관측 공백(UNKNOWN)을
확정 시간에 넣으면 카메라 장애가 주차 확정을 앞당긴다.

MOVING은 정지 후보(STOP_PENDING)를 즉시 초기화하지만, 확정된 에피소드는
`move_confirm_seconds`만큼 이동이 관측돼야 종료한다(T-09에서 정정). 즉시
종료하지 않는 이유는 motion_estimator(436)에 평활화가 없어 bbox가
movement_epsilon만 흔들려도 MOVING이 나오기 때문이다 — 즉시 종료하면 장기
주차가 잡음 한 프레임으로 끊기고, 열린 사건이 해소된 뒤 600초를 새로 쌓아
다시 열린다.

UNKNOWN은 정지 시간에 포함하지 않고 기존 상태도 즉시 종료하지 않는다. 종료 뒤
다시 정지한 차량에는 새로운 parking_episode_id를 발급한다.

**소실된 차량에 ZoneVisitTracker의 레시피를 그대로 옮기면 안 된다.**
ZoneVisitTracker는 사라진 차량에 ABSENT를 계속 먹이면 이탈 확인시간으로
방문이 닫힌다 — force-close는 안전망일 뿐이다. 이 트래커는 정반대다.
`MotionSignal`에는 ABSENT가 없고(소유 파일이라 추가할 수 없다), UNKNOWN은
정지 시간을 누적하지도 기존 상태를 종료하지도 않으므로, 소실된 차량에 어떤
신호를 계속 먹여도(UNKNOWN이든 다른 무엇이든) `update()`는 절대 에피소드를
닫지 않는다. 게다가 `update()`는 신호 종류와 무관하게 `last_updated_at`을
갱신한다 — UNKNOWN도 예외가 아니다. 그래서 "살아있게 유지"하려는 루프는
`prune()`의 방치 판정(`stale_after_seconds`)마저 영원히 미룬다. **여기서는
`prune()`이 소실된 차량을 닫는 유일한 통로이며 안전망이 아니다.** UNKNOWN은
카메라 장애(`source_available=False`)에만 써야 한다 — "이 차량이 이번
프레임에 없었다"는 의미로 UNKNOWN을 먹이면 사건이 영원히 열린 채 남는다.

**규칙이 상태별로 무엇을 내야 하는가** (T-12 `bad_parking` 구현자를 위한 계약,
463에서 MOVING·ENDED 행을 정정 — 아래 참고):

| 에피소드 상태 | 규칙이 낼 신호 | 이유 |
|---|---|---|
| `STOP_PENDING` | `matched=True, confirmable=False` | 후보. 아직 주차가 아니다. bbox가 안정적이라 재분류가 안전하다 |
| `PARKED` | `matched=True, confirmable=True` | 확정 |
| `MOVING` | 규칙을 아예 거치지 않는다 | 아래 참고 |
| `ENDED` | 규칙을 아예 거치지 않는다 | 아래 참고 |

**MOVING·ENDED는 규칙이 아니라 조립자가 처리한다(463, `resolve_scope`류의
446 교훈을 선제 적용).**

ENDED는 조립자가 `IncidentReducer.resolve_episode_scope(parking_episode_id)`를
직접 호출해 해소한다 — 그 시점의 차량 위치로 rule_code(BAD_PARKING/
OUT_OF_ZONE/AISLE_BLOCK 중 무엇이었는지)를 재판정해야 하는데, 차량은
이미 이동 중이라 원래와 다른 rule_code가 나올 수 있고, 추적이 아예
끊겨 `prune()`이 강제 종료한 경우엔 `RuleContext.vehicle`을 채울 스냅샷
자체가 없기 때문이다. `resolve_episode_scope`는 이미 기록된 rule_code를
재사용해 닫으므로 이 문제가 없다.

이 표는 원래 MOVING에서도 규칙이 `matched=True, confirmable=True`를
내라고 했었다(깜빡임 방지 의도). 하지만 MOVING은 "이동이 실제로 진행
중"이라는 뜻이라 매 프레임 bbox가 달라진다 — 그대로 재분류하면 두
스팟에 걸쳐(AMBIGUOUS) BAD_PARKING이던 차량이 이동하며 다른 구역을
지나가는 순간 분류가 바뀌어 `matched=False`가 나가고, 에피소드가 아직
ENDED로 확정되지도 않았는데 원래 사건이 조기에 RESOLVE된다. 그래서
조립자는 MOVING에서 규칙을 아예 안 부르고 기존 EDGE_CONFIRMED 사건을
그대로 둔다 — 깜빡임 방지라는 원래 의도는 그대로 지키면서 조기 해소
위험만 없앤다. `bad_parking.evaluate_open()`은 STOP_PENDING/PARKED
두 상태만 다룬다.

`active_episode()`는 `ZoneVisitTracker.active_visits()`와 달리 네 상태를 전혀
걸러내지 않는다 — 규칙 구현자가 이 표를 보고 직접 판단해야 한다.

**조립자가 지켜야 하는 두 가지가 더 있다.**

- **`ended_vehicle_ids`에 대해 아무것도 할 수 없다.** `MotionEstimator.forget()`에
  대응하는 `forget()`/`discard()`가 이 트래커에는 없다. 추적이 확실히 끊긴 뒤
  `RESOLVE`까지 최대 `stale_after_seconds`(기본 900초)가 걸릴 수 있다는 뜻이다.
  이 지연을 줄이려고 MOVING 프레임을 조작해서는 안 된다.
- **차량별 스냅샷 캐시는 두 트래커 중 더 긴 `stale_after_seconds`만큼 살아
  있어야 한다** — 오늘 기준 900초이지 ZoneVisitTracker의 300초가 아니다. 두
  트래커는 같은 소실 차량을 서로 다른 프레임에서 강제 종료한다(실측 600초
  차이). 구역 쪽 일정으로 캐시를 비우면 주차 쪽 종료가 스냅샷을 못 찾고,
  `RuleContext.vehicle`은 필수 필드라 판정 자체가 막힌다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from src.parking.models import ParkingEpisode, ParkingEpisodeId, ParkingState
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
)


class ParkingEpisodeTracker(Protocol):
    """이동 신호를 STOP_PENDING/PARKED/MOVING/ENDED 에피소드로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observed_at: datetime,
    ) -> ParkingEpisode | None:
        """현재 또는 방금 종료된 에피소드를 반환하고 없으면 None을 반환한다.

        종료(ENDED)는 규칙이 `matched=False`를 내는 근거이므로 반드시 판정에
        도달해야 한다. 관측이 계속되는 차량은 이 반환값으로, 추적이 끊긴
        차량은 `prune()`의 반환값으로 전달된다.
        """

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
        """현재 또는 방금 종료된 에피소드를 반환한다. 없으면 None을 반환한다.

        **physical_vehicle_id당 한 프레임에 최대 한 번만 불러야 한다.** 종료
        (`ENDED`) 슬롯은 다음 호출에서 자기 정리로 지워진다(아래 참고). 같은
        프레임에 같은 차량으로 두 번 부르면, 첫 호출이 반환한 종료를 판정이
        읽기 전에 두 번째 호출의 자기 정리가 그 슬롯을 지워 버려 종료가
        복구 불가능하게 사라진다. 두 카메라가 같은 실물 차량을 봤다면
        호출 전에 하나의 `MotionSignal`로 병합해야 한다 — 이 경합이 실제로
        발생하는 지점이다.
        """

        slot = self._slots.get(physical_vehicle_id)
        ensure_forward_observation(
            observed_at, None if slot is None else slot.last_updated_at
        )
        if slot is not None:
            slot.last_updated_at = observed_at

        if slot is None or slot.is_closed():
            if slot is not None:
                # 종료 슬롯이다. 종료는 닫힌 프레임의 판정이 이미 봤으므로 여기서
                # 지운다 — prune()을 빠뜨려도 다음 관측이 스스로 정리하는
                # 백스톱이다(ZoneVisitTracker와 동일). 이 시점부터 슬롯이 없는
                # 것과 완전히 같게 동작한다.
                del self._slots[physical_vehicle_id]
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
            episode_id=self._new_episode_id(),
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
            # 확정 전에 움직였다. 에피소드는 성립하지 않았으므로(parked_at은
            # None으로 남는다) PARKED가 된 적은 없지만, ENDED로는 보고한다
            # (463, MR !141 리뷰로 발견). prune()의 강제 종료가 미확정
            # STOP_PENDING 후보도 ENDED로 보고하는 것과 같은 이유다 — 이
            # 후보가 이미 규칙에서 matched=True인 CANDIDATE 사건을 열게
            # 했다면, 신고 없이는 그 사건을 resolve_episode_scope로 해소할
            # 방법이 없다. 새 정지 후보는 새 episode_id를 받으므로 이
            # 후보의 사건 키는 다시 평가될 길이 없어, 신고 없이 사라지면
            # IncidentReducer 안에 CANDIDATE가 영원히 남는다(백엔드로
            # 나가는 데이터는 틀리지 않지만 리소스 누수다).
            #
            # 슬롯을 여기서 바로 지우지 않는다 — `_advance_departing`과
            # 같은 이유다. 조립자가 이번 프레임에 `active_episode()`로
            # 이 ENDED를 읽어야 하므로, 슬롯은 이번 프레임의 `prune()`(이미
            # 닫힌 슬롯을 지우는 1단계) 또는 다음 `update()` 호출의 자기
            # 정리가 지운다.
            slot.episode = replace(slot.episode, state=ParkingState.ENDED, ended_at=observed_at)
            return slot.episode

        accumulated = slot.accumulate(observed_at)
        slot.episode = replace(
            slot.episode,
            stationary_observed_seconds=accumulated,
            last_signal=signal,
            last_observed_at=observed_at,
        )
        if accumulated >= self._parked_after_seconds:
            # "정지 시작 + 600초"가 아니라 이 확정 관측 시각을 쓴다. 관측
            # 공백이 있으면 "시작 + 600초"는 실제로 관측된 적 없는 벽시계
            # 값이 되기 때문이다.
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

    def active_episode(self, physical_vehicle_id: PhysicalVehicleId) -> ParkingEpisode | None:
        """이 차량의 현재 에피소드를 반환한다. 순수 읽기이며 상태를 바꾸지 않는다.

        `ENDED` 에피소드도 포함한다 — 규칙이 `matched=False`를 내야
        `IncidentReducer`가 `RESOLVE`를 만들 수 있고, 그러려면 종료를 봐야 한다.
        판정이 끝나면 `prune()`이 그 슬롯을 지운다.

        네 상태를 전혀 걸러내지 않는다 — `ZoneVisitTracker.active_visits()`가
        `INSIDE`/`OUTSIDE`만 남기고 `ENTERING`/`EXITING`을 거르는 것과 다르다.
        `STOP_PENDING`과 `MOVING`도 그대로 나가므로, 규칙 구현자는 모듈
        docstring의 상태별 신호 표를 보고 각 상태에서 무엇을 낼지 직접
        판단해야 한다.
        """

        slot = self._slots.get(physical_vehicle_id)
        return None if slot is None else slot.episode

    def prune(self, now: datetime) -> tuple[ParkingEpisode, ...]:
        """판정이 끝난 뒤 프레임마다 한 번 호출한다. 강제 종료한 에피소드를 반환한다.

        두 가지를 한다.

        1. 이미 `ENDED`인 슬롯을 지운다. 판정은 그 프레임에 `active_episode()`로
           이미 받아 갔다.
        2. `stale_after_seconds` 동안 `update()`가 오지 않은 열린 슬롯을 강제
           종료하고 **반환한다.** 반환값을 버리면 그 차량의 열린 사건이 영원히
           닫히지 않는다 — 조립자는 이번 프레임에 관측된 차량만 순회하므로
           사라진 차량의 종료는 이 반환값으로만 판정에 도달한다.

        **이 트래커에서는 `prune()`이 소실된 차량을 닫는 유일한 통로다 —
        안전망이 아니다.** `ZoneVisitTracker`처럼 사라진 차량에 신호를 계속
        먹여 정상 경로로 닫는 방법이 없다. UNKNOWN은 정지 시간을 누적하지도
        상태를 종료하지도 않고, `update()`는 신호 종류와 무관하게
        `last_updated_at`을 갱신하므로, 무엇을 계속 먹이든 이 슬롯은 절대
        스스로 방치 판정에 걸리지 않는다. `update()`가 멈추는 것, 즉 이
        메서드만이 소실된 차량의 종료를 만든다.

        멱등하지 않다. 한 프레임에 두 번 부르면 첫 호출이 이미 강제 종료한
        슬롯을 반환하며 지웠으므로 두 번째 호출은 빈 튜플을 돌려준다 —
        **첫 호출의 반환값을 버리면 그 종료는 복구할 길이 없다.** 판정보다
        먼저 부르는 것도 같은 이유로 안 된다 — 1단계가 이번 프레임에 관측으로
        닫힌 슬롯을 판정 전에 지워 버린다.
        """

        ensure_forward_observation(now)

        for vehicle_id, slot in list(self._slots.items()):
            if slot.is_closed():
                del self._slots[vehicle_id]

        if self._stale_after_seconds <= 0.0:
            return ()

        forced: list[ParkingEpisode] = []
        for vehicle_id, slot in list(self._slots.items()):
            if (now - slot.last_updated_at).total_seconds() < self._stale_after_seconds:
                continue
            # 미확정 STOP_PENDING 후보도 강제 종료해 ENDED로 보고한다 —
            # parked_at은 None으로 남는다(주차가 확정된 적 없다). 이미
            # matched=True를 낸 후보이므로 추적이 끊기면 반드시 해소해야
            # 하기 때문이다. ZoneVisitTracker가 미확정 ENTERING 후보를
            # 종료로 보고하지 않고 억제하는 것과 다른 선택이다 — 의도적인
            # 차이이며, 나중에 "형제와 똑같이 맞추자"는 리팩터는 아래
            # test_prune_force_closes_an_unconfirmed_candidate_as_ended가
            # 잡아낸다.
            ended = replace(
                slot.episode,
                state=ParkingState.ENDED,
                ended_at=slot.move_candidate_at or slot.episode.last_observed_at,
            )
            forced.append(ended)
            del self._slots[vehicle_id]
        return tuple(forced)

    @staticmethod
    def _new_episode_id() -> ParkingEpisodeId:
        """새로 시작한 정지·주차 행위의 불투명한 수명주기 ID를 발급한다."""

        return ParkingEpisodeId(uuid4())

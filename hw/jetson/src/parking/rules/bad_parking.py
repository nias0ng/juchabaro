"""ParkingEpisode 확정 후 평가하는 선 침범·구역 외·통행 방해 규칙.

`restricted_zone`/`ev_overstay`와 달리 `ZoneVisit`이 아니라 `ParkingEpisode`
(600초 정지 확정, T-09)와 `ParkingAssignment`(대표 주차면, T-10)를 입력으로
받는다(데이터흐름.md §4). 판정은 하나의 프레임 스냅샷으로 우선순위를 매겨
셋 중 하나만 고른다.

1. 통행로(AISLE)를 INSIDE로 막고 있으면 `AISLE_BLOCK` — 배정 상태와 무관하게
   최우선이다. 통행 방해가 더 급한 문제이기 때문이다.
2. 아니면 대표 주차면 배정(`ParkingAssignment.state`)을 본다 —
   `AMBIGUOUS`(두 스팟에 걸침)면 `BAD_PARKING`, `UNASSIGNED`(스팟이 아예
   없음)면 `OUT_OF_ZONE`, `ASSIGNED`(제대로 배정됨)면 위반이 아니다.

세 rule_code 모두 매 프레임 평가해서 신호를 낸다 — 선택되지 않은 코드는
`matched=False`로 나간다. 이래야 지난 프레임엔 다른 코드로 잡혔다가 이번
프레임에 분류가 바뀐 경우(예: AISLE을 벗어나며 AMBIGUOUS로 바뀜) 이전
코드의 사건이 정상적으로 RESOLVE된다. 단, 이 재분류는 `PARKED`(그리고
그 이전 `STOP_PENDING`)에서만 안전하다 — 아래 참고.

**MOVING과 ENDED는 다루지 않는다(463).** 둘 다 이 규칙을 거치지 않고
`IncidentReducer.resolve_episode_scope(parking_episode_id)`가 직접
처리하거나(ENDED), 아무 신호도 안 내 기존 사건을 그대로 둔다(MOVING).

ENDED를 규칙에서 뺀 이유는 그 시점엔 차량이 이미 이동 중이거나 추적이
끊겨 있어 현재 위치로 rule_code를 재구성할 수 없기 때문이다
(`parking_episode_tracker.py`, `parking/incident_reducer.py` 참고).

MOVING을 뺀 이유는 처음엔 놓쳤던 것이다 — MOVING은 "이동이 실제로
진행 중"이라는 뜻이라 매 프레임 bbox가 달라진다. 여기서도 매 프레임
재분류를 하면(원래 설계처럼 matched=True를 계속 냈다면), 예를 들어
원래 두 스팟에 걸쳐(AMBIGUOUS) BAD_PARKING이던 차량이 이동하며 다른
구역을 지나가는 순간 분류가 OUT_OF_ZONE이나 "위반 아님"으로 바뀌어
`matched=False`가 나가고, 에피소드가 아직 ENDED로 확정되지도 않았는데
원래 사건이 조기에 RESOLVE된다. 그래서 MOVING에서는 신호를 아예 안 내
기존 EDGE_CONFIRMED 사건을 그대로 둔다 — PARKED로 되돌아오면 그때
다시 평가되고, 끝내 ENDED가 되면 `resolve_episode_scope`가 정리한다.
STOP_PENDING은 문제없다 — 그 상태는 정지 후보 구간이라 bbox가 이미
안정적이다(움직이는 중이 아니다).

`IncidentKey`의 `zone_id`는 항상 `None`으로 둔다 — 어느 구역이 겹쳤는지에
따라 키가 흔들리면, 같은 사건을 나중에 `matched=False`로 해소하려 할 때
다른 키를 만들어 원래 사건을 찾지 못한다. 스코프는 `parking_episode_id`
하나로 충분하다.
"""

from __future__ import annotations

from src.parking.models import (
    AssignmentState,
    IncidentKey,
    IncidentSignal,
    ParkingEpisode,
    ParkingState,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ZoneType

AISLE_BLOCK = "AISLE_BLOCK"
BAD_PARKING = "BAD_PARKING"
OUT_OF_ZONE = "OUT_OF_ZONE"

_ALL_RULE_CODES = (AISLE_BLOCK, BAD_PARKING, OUT_OF_ZONE)


def evaluate_open(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """`ParkingEpisode`가 STOP_PENDING/PARKED일 때만 판정한다.

    에피소드가 없거나(정지한 적 없음), MOVING(이동 중이라 재분류가
    불안정함), ENDED(조립자가 `resolve_episode_scope`로 직접 처리)면
    신호를 아예 내지 않는다.
    """

    episode = context.parking_episode
    if episode is None or episode.state in (ParkingState.MOVING, ParkingState.ENDED):
        return ()

    confirmable = episode.state is ParkingState.PARKED
    active_code = _classify(context)
    return tuple(
        _signal(context, episode, rule_code=code, matched=(code == active_code), confirmable=confirmable)
        for code in _ALL_RULE_CODES
    )


def _classify(context: RuleContext) -> str | None:
    """현재 스냅샷으로 세 코드 중 어느 것이 성립하는지 고른다. 위반이 아니면 None."""

    if _is_blocking_aisle(context):
        return AISLE_BLOCK

    assignment = context.parking_assignment
    if assignment is None:
        # 아직 배선 전이거나 방어적 상황이다 — 위반을 억지로 만들지 않는다.
        return None
    if assignment.state is AssignmentState.AMBIGUOUS:
        return BAD_PARKING
    if assignment.state is AssignmentState.UNASSIGNED:
        return OUT_OF_ZONE
    return None  # ASSIGNED — 제대로 배정됨, 위반 아님


def _is_blocking_aisle(context: RuleContext) -> bool:
    for visit in context.active_zone_visits:
        if visit.state is not ZoneVisitState.INSIDE:
            continue
        zone = context.zones.get_or_none(visit.zone_id)
        if zone is not None and zone.zone_type is ZoneType.AISLE:
            return True
    return False


def _signal(
    context: RuleContext,
    episode: ParkingEpisode,
    *,
    rule_code: str,
    matched: bool,
    confirmable: bool,
) -> IncidentSignal:
    assignment = context.parking_assignment
    return IncidentSignal(
        key=IncidentKey(
            # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
            physical_vehicle_id=episode.physical_vehicle_id,
            rule_code=rule_code,
            parking_episode_id=episode.episode_id,
        ),
        matched=matched,
        confirmable=confirmable,
        observed_at=context.observed_at,
        evidence={
            "parkingState": episode.state.value,
            "assignmentState": None if assignment is None else assignment.state.value,
        },
    )

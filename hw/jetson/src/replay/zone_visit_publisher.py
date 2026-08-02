"""ZoneVisit 상태 전이를 JSON Lines 파일로 발행한다(465/T-17).

`restricted_zone`은 `VehicleContext`가 없으면 항상 `confirmable=False`라
(`rules/restricted_zone.py`), 파일럿 영상만으로 리플레이하면 백엔드 입차
이벤트가 없어 사건이 outbox까지 확정되지 않는다. §4.7 임계값 산출은 확정된
사건이 아니라 ZoneVisit의 ENTERING→INSIDE 오탐 횟수를 사람이 라벨링한
정답과 비교해 측정하므로, VehicleContext 유무와 무관하게 모든 방문 전이를
그대로 기록해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, TextIO

from src.parking.models import ZoneVisit, ZoneVisitId, ZoneVisitState


class ZoneVisitPublisherError(RuntimeError):
    """방문 전이를 파일에 기록하는 데 실패했다."""


# 상태별로 "언제 관측됐다"고 볼 수 있는 유일한 필드. ENTERING/EXITING은 아직
# 확정 전이라 후보 시각(entered_candidate_at/exit_candidate_at)을 쓰고,
# INSIDE/ENDED/CANCELED는 확정 시각(entered_at/ended_at)을 쓴다 — 새 upstream
# 필드를 만들지 않고 ZoneVisit이 이미 들고 있는 값 중 하나를 고르는 것뿐이다.
# ENDED/CANCELED는 둘 다 종료 시각을 ended_at 하나에만 담는다(models.py의
# ZoneVisit.__post_init__ 불변식 참고).
_OBSERVED_AT_FIELD_BY_STATE: dict[ZoneVisitState, str] = {
    ZoneVisitState.ENTERING: "entered_candidate_at",
    ZoneVisitState.INSIDE: "entered_at",
    ZoneVisitState.EXITING: "exit_candidate_at",
    ZoneVisitState.ENDED: "ended_at",
    ZoneVisitState.CANCELED: "ended_at",
}


def zone_visit_to_jsonable(visit: ZoneVisit) -> dict[str, Any]:
    """`ZoneVisit`을 JSON 직렬화 가능한 dict(camelCase)로 변환한다.

    `src/communication/outbox.py`의 `transition_to_jsonable`과 같은 와이어
    규칙(camelCase, UUID는 문자열, datetime은 ISO 8601)을 따른다.

    `observedAt`은 현재 상태에 맞는 시각 하나를 골라 파생한 필드다 — 상태별로
    어떤 datetime이 "이 전이가 관측된 시각"인지가 다르므로(예: INSIDE는
    entered_at, EXITING은 exit_candidate_at), 소비자가 상태마다 다른 필드를
    찾지 않고 한 필드만 보고 정렬·비교할 수 있게 한다.
    """

    observed_at_field = _OBSERVED_AT_FIELD_BY_STATE[visit.state]
    observed_at = getattr(visit, observed_at_field)
    return {
        "zoneVisitId": str(visit.visit_id),
        "physicalVehicleId": str(visit.physical_vehicle_id),
        "zoneId": visit.zone_id,
        "state": visit.state.value,
        "observedAt": None if observed_at is None else observed_at.isoformat(),
        "enteredCandidateAt": None if visit.entered_candidate_at is None else visit.entered_candidate_at.isoformat(),
        "enteredAt": None if visit.entered_at is None else visit.entered_at.isoformat(),
        "exitCandidateAt": None if visit.exit_candidate_at is None else visit.exit_candidate_at.isoformat(),
        "endedAt": None if visit.ended_at is None else visit.ended_at.isoformat(),
        "terminationReason": visit.termination_reason,
    }


class ZoneVisitJsonlPublisher:
    """ZoneVisit 전이를 한 줄에 하나씩 JSONL로 쓴다.

    `sort_keys`는 쓰지 않는다 — `zone_visit_to_jsonable`이 항상 같은 순서로
    dict를 만들므로 값 자체의 결정론이 이미 순서를 고정한다(outbox.py와 동일한
    근거).
    """

    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._handle: TextIO | None = None

    def __enter__(self) -> "ZoneVisitJsonlPublisher":
        self.open()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def open(self) -> None:
        """출력 파일을 새로 만든다. 상위 디렉터리가 없으면 만든다."""

        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("w", encoding="utf-8", newline="\n")

    def publish(self, visit: ZoneVisit) -> None:
        """방문 전이 한 건을 JSON 한 줄로 쓴다."""

        if self._handle is None:
            raise ZoneVisitPublisherError("JSONL 파일이 열려 있지 않습니다. open()을 먼저 호출하세요.")
        line = json.dumps(zone_visit_to_jsonable(visit), ensure_ascii=False) + "\n"
        try:
            self._handle.write(line)
        except OSError as exc:
            raise ZoneVisitPublisherError(f"zone visit 파일에 쓰지 못했습니다({self._path}): {exc}") from exc

    def close(self) -> None:
        """파일 핸들을 닫는다.

        버퍼링 때문에 디스크 꽉 참 같은 쓰기 실패가 `write()`가 아니라
        `close()`의 flush에서 터질 수 있다 — `publish()`와 같은 방식으로
        감싸지 않으면 `ZoneVisitPublisherError`를 두는 의미가 반쪽만 남는다.
        """

        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError as exc:
                raise ZoneVisitPublisherError(f"zone visit 파일을 닫지 못했습니다({self._path}): {exc}") from exc


class DedupingZoneVisitPublisher:
    """visit_id별 마지막으로 발행한 상태를 기억해, 상태가 바뀐 전이만 발행한다.

    `zone_visit_tracker.py`의 `_advance_inside`는 PRESENT가 이어지는 동안
    같은 INSIDE 방문을 프레임마다 그대로 반환한다 — 조립기가 그걸 매 프레임
    그대로 발행하면 한 차량이 한 구역에 20프레임 머무를 때 거의 같은 레코드가
    20줄 나온다. 실제로 의미 있는 것은 ENTERING/INSIDE/EXITING/ENDED/CANCELED 다섯
    상태로의 전이뿐이므로, 여기서 visit_id별 마지막 상태를 기억해 두고 상태가
    바뀌었을 때(또는 처음 보는 visit_id일 때)만 내부 발행기에 넘긴다.

    CLI(`scripts/replay_pilot_video.py`)와 결정론 테스트가 같은 dedup 규칙을
    쓰도록 여기 하나로 모아 둔다 — 두 곳에 같은 로직을 복붙하면 나중에
    한쪽만 고쳐 조용히 어긋날 자리가 생긴다.
    """

    def __init__(self, publisher: ZoneVisitJsonlPublisher) -> None:
        self._publisher = publisher
        self._last_published_state: dict[ZoneVisitId, ZoneVisitState] = {}

    def publish_all(self, visits: Iterable[ZoneVisit]) -> int:
        """상태가 바뀐 방문만 발행하고, 실제로 발행한 건수를 반환한다."""

        published = 0
        for visit in visits:
            if self._last_published_state.get(visit.visit_id) == visit.state:
                continue
            self._publisher.publish(visit)
            self._last_published_state[visit.visit_id] = visit.state
            published += 1
        return published

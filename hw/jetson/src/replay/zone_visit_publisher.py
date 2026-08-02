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
from typing import Any, TextIO

from src.parking.models import ZoneVisit


class ZoneVisitPublisherError(RuntimeError):
    """방문 전이를 파일에 기록하는 데 실패했다."""


def zone_visit_to_jsonable(visit: ZoneVisit) -> dict[str, Any]:
    """`ZoneVisit`을 JSON 직렬화 가능한 dict(camelCase)로 변환한다.

    `src/communication/outbox.py`의 `transition_to_jsonable`과 같은 와이어
    규칙(camelCase, UUID는 문자열, datetime은 ISO 8601)을 따른다.
    """

    return {
        "zoneVisitId": str(visit.visit_id),
        "physicalVehicleId": str(visit.physical_vehicle_id),
        "zoneId": visit.zone_id,
        "state": visit.state.value,
        "enteredCandidateAt": None if visit.entered_candidate_at is None else visit.entered_candidate_at.isoformat(),
        "enteredAt": None if visit.entered_at is None else visit.entered_at.isoformat(),
        "exitCandidateAt": None if visit.exit_candidate_at is None else visit.exit_candidate_at.isoformat(),
        "exitedAt": None if visit.exited_at is None else visit.exited_at.isoformat(),
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
        """파일 핸들을 닫는다."""

        handle, self._handle = self._handle, None
        if handle is not None:
            handle.close()

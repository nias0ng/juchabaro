"""위반 이벤트를 백엔드 `/api/hw/parking-events`로 전송하는 `ResultPublisher` 구현(370번).

`jetson_vehicle_tracking_baseline.py`의 `ResultPublisher` Protocol을 그대로 만족하므로
(구조적 타이핑), 그 파일을 수정하지 않고도 `publisher = HttpResultPublisher(...)`로
교체해서 쓸 수 있다. 실제 CLI 연결은 별도 커밋에서 진행한다.

**CLI에 연결할 때 반드시 확인할 것**: `run_monitor`의 메인 루프
(`for event in monitor.update(detections): publisher.publish(event)`)는
`publish()` 호출을 try/except로 감싸지 않는다. 지금까지는 `StdoutResultPublisher`가
실질적으로 실패하지 않아 문제가 없었지만, 이 클래스의 `publish()`는 네트워크
장애·백엔드 다운 시 `HttpPublishError`를 던진다 — 그대로 연결하면 **백엔드가
잠깐만 응답 안 해도 차량 감지 루프 전체가 죽는다.** 연결 시 이 예외를 잡아서
로그만 남기고 다음 프레임으로 계속 진행하도록 감싸야 한다.

미확정/가정 사항(백엔드 팀 확인 필요):
- `POST /api/hw/parking-events`의 실제 요청 스키마가 아직 정의되지 않아(백엔드에
  컨트롤러 자체가 없음, `ParkingEvent` 엔티티만 존재), 아래 payload 필드명은 그
  엔티티 컬럼명을 참고한 추정치다.
- `ParkingEvent.session`/`vehicle`이 `nullable=false`인데, 번호판 매칭에 실패한
  트랙(`plate_number=None`, PLATE_UNMATCHED)은 어떤 세션/차량인지 특정할 수 없다.
  이번 구현은 이 경우 전송을 건너뛰고 경고 로그만 남긴다 — 백엔드가 미확정
  차량을 받아들이는 방법(nullable 완화, 별도 테이블 등)이 정해지면 갱신이 필요하다.
- `ParkingEvent.violationRatio`가 `Integer`라, `ViolationEvent.overlap_ratio`
  (0.0~1.0 float, 차체 또는 구역 면적 기준)를 반올림해 0~100 정수(%)로 변환한다.
- `ViolationStatus` → 백엔드 `event_type` 매핑은 OUT_OF_ZONE만 이름이 정확히
  일치하고 나머지(RESTRICTED_ZONE/LINE_CROSS/AISLE_BLOCK)는 ERD의 5종
  event_type과 1:1로 안 떨어진다(317번 MR 리뷰에서 팀 확인 필요로 남겨둔 항목).
  아래 `DEFAULT_STATUS_TO_EVENT_TYPE`은 그때까지 쓰는 최선의 추정 매핑이며,
  생성자의 `status_to_event_type`으로 언제든 교체할 수 있다. (EV_OVERSTAY는
  이 브랜치가 갈라진 시점엔 develop에 없어 매핑에서 빠져있다 — 319번 병합 후
  추가 필요, 위 test로 누락이 잡힌다.)
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

LOGGER = logging.getLogger("http_result_publisher")

PARKING_EVENTS_PATH = "/api/hw/parking-events"

# 임시 매핑(팀 확인 필요) — OUT_OF_ZONE만 ERD event_type과 이름이 정확히 같다.
#
# 주의: 이 딕셔너리는 이 파일이 독립적으로 관리하며 jetson_vehicle_tracking_baseline.py의
# ViolationStatus enum과 자동으로 동기화되지 않는다 — 그쪽에 새 상태가 추가되면(예:
# EV_OVERSTAY, 319번, 이 브랜치가 갈라진 시점엔 아직 develop에 없었음) 여기도 수동으로
# 추가해야 한다. test_http_result_publisher.py의
# test_default_mapping_covers_every_violation_status_except_none_and_observing가
# 그 누락을 테스트 실패로 잡아준다.
DEFAULT_STATUS_TO_EVENT_TYPE: dict[str, str] = {
    "DOUBLE_PARK": "DOUBLE_PARKING",
    "RESTRICTED_ZONE": "DISABLED_ZONE_VIOLATION",
    "OUT_OF_ZONE": "OUT_OF_ZONE",
    "LINE_CROSS": "BAD_PARKING",
    "AISLE_BLOCK": "BAD_PARKING",
}


class HttpPublishError(RuntimeError):
    """백엔드로의 위반 이벤트 전송이 실패한 경우."""


class HttpResultPublisher:
    """`ViolationEvent`를 백엔드 `POST /api/hw/parking-events`로 전송한다.

    번호판 매칭에 실패한 이벤트(`plate_number is None`)는 전송을 건너뛰고
    경고 로그만 남긴다 — 백엔드 `ParkingEvent.vehicle`이 `nullable=false`라
    현재 스키마로는 미확정 차량을 저장할 방법이 없기 때문이다(팀 확인 필요).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        status_to_event_type: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        # (주의) `status_to_event_type or DEFAULT...`로 쓰면 호출자가 명시적으로 빈
        # dict({})를 넘겨도 falsy라서 조용히 기본값으로 대체돼버린다 — None 체크로 구분한다.
        self._status_to_event_type = dict(
            DEFAULT_STATUS_TO_EVENT_TYPE if status_to_event_type is None else status_to_event_type
        )
        self._timeout_seconds = timeout_seconds

    def publish(self, event: Any) -> None:
        """`ViolationEvent` 한 건을 백엔드로 전송한다. 실패하면 `HttpPublishError`를 던진다."""

        if event.plate_number is None:
            LOGGER.warning(
                "번호판 매칭 실패(plate_number=None)로 track_id=%s의 %s 이벤트를 이번엔 "
                "전송하지 않습니다(백엔드 parking_events.vehicle_id가 NOT NULL이라 미확정 "
                "차량을 저장할 방법이 아직 없음 — 팀 확인 필요).",
                event.track_id,
                event.status,
            )
            return

        event_type = self._status_to_event_type.get(event.status.value)
        if event_type is None:
            raise HttpPublishError(f"status_to_event_type에 매핑이 없는 ViolationStatus입니다: {event.status}")

        payload: dict[str, Any] = {
            "trackingId": event.track_id,
            "plateNumber": event.plate_number,
            "zoneId": event.zone_id,
            "eventType": event_type,
            "reason": f"{event.status.value} (자동 감지)",
            "violationRatio": round(event.overlap_ratio * 100),
            "detectedAt": event.detected_at.isoformat(),
        }
        self._post(payload)

    def _post(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            f"{self._base_url}{PARKING_EVENTS_PATH}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-HW-API-Key": self._api_key,
            },
        )
        try:
            with urllib_request.urlopen(req, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status >= 300:
                    raise HttpPublishError(f"백엔드가 실패 응답을 반환했습니다: HTTP {status}")
        except HTTPError as exc:
            raise HttpPublishError(f"백엔드 요청이 거부됐습니다(HTTP {exc.code}): {exc.reason}") from exc
        except URLError as exc:
            raise HttpPublishError(f"백엔드({self._base_url})에 연결할 수 없습니다: {exc.reason}") from exc

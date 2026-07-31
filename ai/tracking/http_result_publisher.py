"""위반 이벤트를 백엔드 `POST /api/hw/parking-events`로 전송하는 `ResultPublisher` 구현(370번).

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

## 이 payload가 따르는 계약

팀 공식 API 명세(`docs/api명세/api hw parking-events *.md`)의 요청 스키마를 따른다.
필수 필드는 `sessionId` / `eventType` / `reason` / `detectedAt` / `images`(1장 이상)이고
`violationRatio`는 선택이다. 명세에 없는 필드는 보내지 않는다 — 이전 구현이 보내던
`trackingId` / `plateNumber` / `zoneId` 3개가 여기서 빠졌다. 특히 `trackingId`는
**의미가 다른 값을 같은 이름으로 보내고 있었다**: 명세의 `trackingId`는 RPi가 입차
시 발급해 출차까지 유지하는 방문 UUID(문자열)인데, 구현은 YOLO 트래커의 프레임
단위 정수 ID를 넣고 있었다. 백엔드는 차량·구역을 `sessionId`로 역참조하므로
`plateNumber`/`zoneId`도 요청 스키마에 없다.

## 미해결 항목 (`docs/superpowers/specs/주차관련 백엔드 계약.md` §11에 정리)

- **`sessionId`가 도착하지만 판정까지 전달되지 않는다.** 명세에서
  `POST /api/hw/parking/entry`는 RPi가 호출하고 그 응답으로만 `sessionId`가 나온다.
  전달 경로는 383번(`entry_event_intake.py`)이 이미 만들어 뒀다 — RPi가
  `POST /internal/entry-events`로 그 응답을 그대로 넘겨주고
  `IncomingEntryEvent.session_id`로 파싱된다. **그런데 `to_entry_event()`가 그 값을
  버린다** — `EntryEvent`는 `plate_number`/`captured_at`/`gate_tracking_id`만 싣고,
  `TrackState`·`ViolationEvent`에도 `session_id` 자리가 없다. 즉 남은 일은 백엔드
  협의가 아니라 **젯슨 내부 배관**(`EntryEvent` → `TrackState` → `ViolationEvent`로
  `session_id`를 흘려보내기)이다. 그때까지 이 클래스는 `session_id_resolver`를
  주입받고, 해결에 실패하면 전송을 건너뛰고 경고만 남긴다(감지 루프를 죽이지 않는다).
- **`images`를 만들 방법이 없다.** 명세는 `imageUrl`(저장 경로)을 필수로 요구하지만
  명세 어디에도 이미지 업로드 엔드포인트가 없다. 업로드 경로가 정해질 때까지
  `image_supplier`를 주입받고, 비어 있으면 역시 건너뛴다. **데모 차단 항목이다.**
- **`violationRatio`의 타입이 명세와 DB에서 다르다.** 명세는 `DOUBLE 0.0~1.0`인데
  `V1__init_schema.sql`의 `violation_ratio`는 `INT NULL`이고 엔티티도 `Integer`다.
  0.43을 그대로 보내면 정수 컬럼에서 0으로 잘린다. 어느 쪽이 맞는지 백엔드가 정하기
  전까지는 **실제로 저장되는 쪽**(정수 퍼센트)에 맞춰 0~100으로 보낸다.
  명세대로 확정되면 `_violation_ratio`만 고치면 된다.
- **재전송이 409에 막힌다.** 젯슨은 네트워크 실패 시 outbox에서 재전송하는데, 명세는
  "동일 세션에 동일 유형의 미해결 사건"을 `409 Conflict`로 막는다. 계약 문서가 요청한
  `incidentId`+`revision` 멱등 수단이 명세에 반영되지 않아, 재전송과 진짜 중복을
  구분할 방법이 없다. 그래서 이 구현은 **409를 성공으로 간주한다**(이미 등록된
  사건이므로 outbox에서 지워도 안전하다는 판단). 멱등 계약이 확정되면 재검토해야 한다.

`ViolationStatus` → 명세 `eventType` 매핑은 `DEFAULT_STATUS_TO_EVENT_TYPE`에 있다.
명세의 `eventType`은 5종(`BAD_PARKING`, `DOUBLE_PARKING`, `DISABLED_ZONE_VIOLATION`,
`EV_OVERSTAY`, `OUT_OF_ZONE`)뿐이라, 계약 문서가 추가를 요청한 `AISLE_BLOCK`과
`EV_ZONE_VIOLATION`이 없다. `OUT_OF_ZONE`과 `EV_OVERSTAY`(319번)는 이름이 정확히
일치하지만, 나머지는 접어서 보내야 한다 — 통행로 방해(`AISLE_BLOCK`)와 주차선 침범
(`LINE_CROSS`)이 둘 다 `BAD_PARKING`으로 합쳐지고, 전기차 구역 무자격 점유는
장애인 구역과 같은 `DISABLED_ZONE_VIOLATION`으로 나간다 — 표시 문구가 사실과
달라지는 손실이며, enum 2종이 추가되면 매핑만 고치면 된다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

LOGGER = logging.getLogger("http_result_publisher")

PARKING_EVENTS_PATH = "/api/hw/parking-events"

# 와이어로 나가는 시각의 시간대. 명세의 모든 DATETIME 예시가 `+09:00`이고, 백엔드
# `ParkingEvent.detectedAt`은 offset이 없는 `LocalDateTime`이다. UTC(`+00:00`)로 보내면
# 백엔드가 offset을 떼는 순간 벽시계가 9시간 이르게 저장되므로 KST로 변환해서 보낸다.
# (백엔드가 `OffsetDateTime`으로 받는다면 KST든 UTC든 같은 시점이라 무해하다.)
WIRE_TIMEZONE = timezone(timedelta(hours=9))

# 명세 `eventType` 5종으로의 매핑 — OUT_OF_ZONE/EV_OVERSTAY만 이름이 정확히 같고,
# 명세에 `AISLE_BLOCK`/`EV_ZONE_VIOLATION`이 없어 AISLE_BLOCK과 LINE_CROSS가
# BAD_PARKING으로 합쳐진다(모듈 docstring 참고).
#
# 주의: 이 딕셔너리는 이 파일이 독립적으로 관리하며 jetson_vehicle_tracking_baseline.py의
# ViolationStatus enum과 자동으로 동기화되지 않는다 — 그쪽에 새 상태가 추가되면 여기도
# 수동으로 추가해야 한다. test_http_result_publisher.py의
# test_default_mapping_covers_every_violation_status_except_none_and_observing가
# 그 누락을 테스트 실패로 잡아준다.
DEFAULT_STATUS_TO_EVENT_TYPE: dict[str, str] = {
    "DOUBLE_PARK": "DOUBLE_PARKING",
    "RESTRICTED_ZONE": "DISABLED_ZONE_VIOLATION",
    "OUT_OF_ZONE": "OUT_OF_ZONE",
    "LINE_CROSS": "BAD_PARKING",
    "AISLE_BLOCK": "BAD_PARKING",
    "EV_OVERSTAY": "EV_OVERSTAY",
}

# 명세 `reason`("AI 판단 근거", 필수)에 넣을 사람이 읽는 문장. 명세 예시가
# "주차구역 외부 침범 비율이 40% 이상입니다." 형태의 한국어 문장이라 그에 맞춘다.
# 이전 구현은 `"DOUBLE_PARK (자동 감지)"` 같은 enum 이름을 그대로 보내고 있었는데,
# 이 값은 관리자 화면과 차주 알림에 그대로 노출되는 자리다.
DEFAULT_STATUS_TO_REASON: dict[str, str] = {
    "DOUBLE_PARK": "다른 차량이 주차된 구역을 침범했습니다(이중주차).",
    "RESTRICTED_ZONE": "전용 주차구역을 이용 자격 없이 점유했습니다.",
    "OUT_OF_ZONE": "지정된 주차구역 밖에 주차했습니다.",
    "LINE_CROSS": "주차선을 침범해 주차했습니다.",
    "AISLE_BLOCK": "통행로를 막고 주차했습니다.",
    "EV_OVERSTAY": "전기차 충전구역 허용 시간을 초과해 점유했습니다.",
}


class HttpPublishError(RuntimeError):
    """백엔드로의 위반 이벤트 전송이 실패한 경우."""


class HttpResultPublisher:
    """`ViolationEvent`를 백엔드 `POST /api/hw/parking-events`로 전송한다.

    명세 필수 필드 중 젯슨이 아직 만들 수 없는 두 가지(`sessionId`, `images`)는
    주입받는다. 어느 쪽이든 확보되지 않으면 **전송을 건너뛰고 경고만 남긴다** —
    감지 루프를 죽이지 않는 것이 우선이고, 어차피 필수 필드가 빠진 요청은 백엔드가
    400으로 거부하기 때문이다. 건너뛴 사건은 JSONL 발행기가 로컬에 남긴다
    (계약 문서 §9).

    Args:
        session_id_resolver: `ViolationEvent`를 받아 주차 세션 ID를 돌려주는 함수.
            확정할 수 없으면 `None`을 돌려준다. 미지정이면 항상 건너뛴다.
        image_supplier: `ViolationEvent`를 받아 명세 `images` 항목 목록을 돌려주는
            함수. 각 항목은 `imageUrl`/`imageType`/`capturedAt` 키를 갖는다.
            미지정이거나 빈 목록이면 건너뛴다.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        session_id_resolver: Callable[[Any], int | None] | None = None,
        image_supplier: Callable[[Any], Sequence[Mapping[str, Any]]] | None = None,
        status_to_event_type: dict[str, str] | None = None,
        status_to_reason: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session_id_resolver = session_id_resolver
        self._image_supplier = image_supplier
        # (주의) `status_to_event_type or DEFAULT...`로 쓰면 호출자가 명시적으로 빈
        # dict({})를 넘겨도 falsy라서 조용히 기본값으로 대체돼버린다 — None 체크로 구분한다.
        self._status_to_event_type = dict(
            DEFAULT_STATUS_TO_EVENT_TYPE if status_to_event_type is None else status_to_event_type
        )
        self._status_to_reason = dict(
            DEFAULT_STATUS_TO_REASON if status_to_reason is None else status_to_reason
        )
        self._timeout_seconds = timeout_seconds

    def publish(self, event: Any) -> None:
        """`ViolationEvent` 한 건을 백엔드로 전송한다. 실패하면 `HttpPublishError`를 던진다."""

        event_type = self._status_to_event_type.get(event.status.value)
        if event_type is None:
            raise HttpPublishError(f"status_to_event_type에 매핑이 없는 ViolationStatus입니다: {event.status}")

        session_id = self._session_id_resolver(event) if self._session_id_resolver is not None else None
        if session_id is None:
            LOGGER.warning(
                "주차 세션 ID를 확정할 수 없어 track_id=%s의 %s 사건을 전송하지 않습니다"
                "(명세상 sessionId는 필수인데 RPi 입차 응답에서 젯슨으로 넘어오는 경로가 아직 "
                "정의되지 않았습니다 — 계약 문서 §11.1).",
                event.track_id,
                event.status.value,
            )
            return

        images = self._collect_images(event)
        if not images:
            LOGGER.warning(
                "사건 이미지를 만들 수 없어 track_id=%s의 %s 사건을 전송하지 않습니다"
                "(명세상 images는 1장 이상 필수인데 imageUrl을 만들 업로드 엔드포인트가 "
                "명세에 없습니다 — 계약 문서 §11.2).",
                event.track_id,
                event.status.value,
            )
            return

        payload: dict[str, Any] = {
            "sessionId": session_id,
            "eventType": event_type,
            "reason": self._reason(event),
            "violationRatio": self._violation_ratio(event),
            "detectedAt": self._wire_datetime(event.detected_at),
            "images": images,
        }
        self._post(payload)

    def _reason(self, event: Any) -> str:
        """명세 `reason`(필수)에 넣을 사람이 읽는 판단 근거 문장을 만든다."""

        base = self._status_to_reason.get(event.status.value, f"{event.status.value} 사건이 감지되었습니다.")
        # EV_OVERSTAY는 침범 비율이 아니라 점유 시간으로 판정된다(319번) — 겹침 비율을
        # 붙이면 위반 근거를 잘못 설명한다. 판정에 쓰인 시계는 dwell_seconds가 아니라
        # occupancy_seconds다(ViolationEvent docstring).
        if event.status.value == "EV_OVERSTAY":
            return f"{base} (점유 {round(event.occupancy_seconds / 60)}분)"
        # OUT_OF_ZONE은 매핑되는 구역이 없어 overlap_ratio가 항상 0.0으로 발행된다
        # (ViolationEvent docstring) — 그 경우 "침범 비율 0%"를 덧붙이면 오해를 부른다.
        if event.overlap_ratio > 0:
            return f"{base} (침범 비율 {round(event.overlap_ratio * 100)}%)"
        return base

    @staticmethod
    def _violation_ratio(event: Any) -> int:
        """`overlap_ratio`(0.0~1.0)를 백엔드가 저장하는 0~100 정수 퍼센트로 바꾼다.

        명세는 `DOUBLE 0.0~1.0`이라고 적고 있으나 실제 컬럼(`violation_ratio INT`)과
        엔티티(`Integer`)가 정수다 — 모듈 docstring의 미해결 항목 참고. 저장되는 쪽에
        맞춘다.
        """

        return round(event.overlap_ratio * 100)

    @staticmethod
    def _wire_datetime(value: datetime) -> str:
        """명세 DATETIME(ISO 8601, 시간대 포함) 형태로 직렬화한다.

        naive datetime은 시간대를 추측하지 않고 거부한다 — 조용히 UTC로 가정하면
        9시간 어긋난 시각이 그대로 저장된다.
        """

        if value.tzinfo is None:
            raise HttpPublishError(
                f"시간대 정보가 없는 detected_at은 전송할 수 없습니다(어느 시간대인지 추측하지 않습니다): {value!r}"
            )
        return value.astimezone(WIRE_TIMEZONE).isoformat()

    def _collect_images(self, event: Any) -> list[dict[str, Any]]:
        """명세 `images` 배열을 만든다. 공급자가 없으면 빈 목록을 돌려준다."""

        if self._image_supplier is None:
            return []
        images: list[dict[str, Any]] = []
        for item in self._image_supplier(event):
            try:
                captured_at = item["capturedAt"]
                image = {
                    "imageUrl": str(item["imageUrl"]),
                    "imageType": str(item["imageType"]),
                    "capturedAt": (
                        self._wire_datetime(captured_at) if isinstance(captured_at, datetime) else str(captured_at)
                    ),
                }
            except KeyError as exc:
                raise HttpPublishError(
                    f"image_supplier가 명세 필수 키를 빠뜨렸습니다({exc}): {item!r} "
                    "— imageUrl/imageType/capturedAt이 모두 필요합니다."
                ) from exc
            images.append(image)
        return images

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
            # 409 = "동일 세션에 동일 유형의 미해결 사건이 존재함"(명세). outbox 재전송이
            # 여기 걸리므로 실패로 다루면 같은 사건을 영원히 재시도한다 — 이미 등록됐다는
            # 뜻이므로 성공으로 간주한다(모듈 docstring의 멱등 미해결 항목 참고).
            if exc.code == 409:
                LOGGER.info(
                    "백엔드에 이미 등록된 사건입니다(HTTP 409) — 전송 성공으로 처리합니다: %s",
                    exc.reason,
                )
                return
            raise HttpPublishError(f"백엔드 요청이 거부됐습니다(HTTP {exc.code}): {exc.reason}") from exc
        except URLError as exc:
            raise HttpPublishError(f"백엔드({self._base_url})에 연결할 수 없습니다: {exc.reason}") from exc

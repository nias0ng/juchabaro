"""라즈베리파이가 보내는 입차 이벤트를 받아 `ViolationMonitor`로 연결한다(383번, 재설계).

**아키텍처가 이 MR의 최초 버전과 반대다.** 처음엔 젯슨이 백엔드
`POST /hw/parking/entry`를 직접 호출하는 클라이언트(`HttpEntryReporter`)를
만들었으나, `hw/raspberry-pi/src/communication`(박신영, 392번)에서 실제
흐름을 확인한 결과:

    라즈베리파이 --(OCR 결과)--> 백엔드 `POST /hw/parking/entry`
                                        |
                                        v (ALLOW/REVIEW/DENY + 차량 정보)
    라즈베리파이 --(그 결과 그대로)--> 젯슨 `POST /internal/entry-events`

백엔드 호출은 라즈베리파이가 이미 담당한다(`BackendClient`). 젯슨이 할 일은
그 결과를 **받아서** 기존 `ViolationMonitor.add_entry_event()` 매칭 큐에
넣어주는 것뿐이다. 그래서 이 파일은 outbound HTTP 클라이언트가 아니라
payload 파싱 + 멱등 처리 로직만 담당한다 — 실제 HTTP 서버(FastAPI)
라우팅은 `hw/jetson`에 `ai/tracking`을 연결하는 별도의 더 큰 통합 작업이
먼저 필요해 이번 MR 범위 밖이다(아래 "미해결" 참고).

`trackingId`는 ByteTrack의 정수 `track_id`가 아니라 **라즈베리파이가 입차
건마다 발급하는 UUID**다(박신영 MR 리뷰 확인). 이름이 비슷해 혼동하기
쉬우므로 `EntryEvent`/`TrackState`에는 `gate_tracking_id`로 다른 이름을
붙였다.

미해결/후속 필요(박신영 MR 리뷰 지적):
- `_try_match_entry_event`는 `entry_match_window_seconds`(기본 10초) 안에
  매칭 못 하면 이벤트를 조용히 버리고, 실패했다는 신호를 라즈베리파이에
  돌려줄 방법이 없다 — 재시도도 안 된다. 이 모듈은 그 문제를 고치지
  않는다(더 큰 설계 결정 필요). 파일럿에서 순간적 가림·인식 지연 빈도를
  보고 창을 넓히거나, 실패 콜백/폴링 엔드포인트를 추가할지 팀 확인 필요.
- 실제 FastAPI 라우트(`POST /internal/entry-events`) 등록과, 그 라우트가
  들고 있을 `ViolationMonitor` 인스턴스 배선은 `hw/jetson`에 아직 없다.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from jetson_vehicle_tracking_baseline import EntryEvent, ViolationMonitor


class EntryEventIntakeError(ValueError):
    """수신한 입차 이벤트 payload가 계약을 위반한 경우."""


@dataclass(frozen=True, slots=True)
class IncomingEntryEvent:
    """라즈베리파이 `JetsonEntryRequest.to_payload()`가 보내는 payload를 그대로 옮긴 것.

    필드명·의미는 `hw/raspberry-pi/src/communication/schemas.py`의
    `JetsonEntryRequest`와 반드시 같아야 한다 — 그쪽이 실제 wire 계약의
    출처다.
    """

    tracking_id: str
    recognized_plate_number: str
    entry_time: datetime
    access_decision: str
    registered: bool
    vehicle_id: int | None
    is_disabled_vehicle: bool | None
    is_electric: bool | None
    vehicle_status: str | None
    session_id: int | None
    duplicate_request: bool

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "IncomingEntryEvent":
        """수신 JSON을 파싱한다. 필수 필드 누락·타입 오류는 `EntryEventIntakeError`로 감싼다."""

        try:
            entry_time = datetime.fromisoformat(str(payload["entryTime"]))
            if entry_time.tzinfo is None:
                raise ValueError("entryTime은 timezone-aware여야 합니다(naive datetime 불가).")
            return cls(
                tracking_id=str(payload["trackingId"]),
                recognized_plate_number=str(payload["recognizedPlateNumber"]),
                entry_time=entry_time,
                access_decision=str(payload["accessDecision"]),
                registered=bool(payload["registered"]),
                vehicle_id=payload.get("vehicleId"),
                is_disabled_vehicle=payload.get("isDisabledVehicle"),
                is_electric=payload.get("isElectric"),
                vehicle_status=payload.get("vehicleStatus"),
                session_id=payload.get("sessionId"),
                duplicate_request=bool(payload["duplicateRequest"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise EntryEventIntakeError(f"입차 이벤트 payload가 올바르지 않습니다: {payload!r} ({exc})") from exc

    def to_entry_event(self) -> EntryEvent:
        """매칭 큐에 넣을 `EntryEvent`로 변환한다.

        `accessDecision`이 DENY(미등록 차량)여도 변환한다 — 미등록 차량도
        여전히 카메라에 잡히고 위반 여부를 판정해야 하는 실제 차량이다.
        DENY를 여기서 걸러내면 미등록 차량은 번호판 없이(`plate_number=None`
        상태 그대로) 위반 판정을 받게 되어, 관리자가 조회할 근거(인식된
        번호판)가 오히려 사라진다.
        """

        return EntryEvent(
            plate_number=self.recognized_plate_number,
            captured_at=self.entry_time,
            gate_tracking_id=self.tracking_id,
            session_id=self.session_id,
            vehicle_id=self.vehicle_id,
            is_disabled_vehicle=self.is_disabled_vehicle,
            is_electric=self.is_electric,
        )


class EntryEventIntake:
    """멱등키(Idempotency-Key) 기준으로 중복을 걸러낸 뒤 `ViolationMonitor`에 입차 이벤트를 넘긴다.

    라즈베리파이는 네트워크 재시도 시 같은 Idempotency-Key로 같은 이벤트를
    다시 보낼 수 있다. 그때마다 `add_entry_event`를 또 호출하면 매칭 대기열에
    같은 번호판이 중복으로 쌓여, 그사이 진짜로 새로 입차한 다른 차량과 잘못
    매칭될 위험이 있다 — 그래서 최근 처리한 키를 기억해 재전송을 무시한다.
    """

    def __init__(self, monitor: ViolationMonitor, *, max_remembered_keys: int = 1000) -> None:
        if max_remembered_keys < 1:
            raise ValueError(f"max_remembered_keys는 1 이상이어야 합니다: {max_remembered_keys}")
        self._monitor = monitor
        self._max_remembered_keys = max_remembered_keys
        # dict를 삽입 순서 유지되는 set처럼 쓴다(값은 안 씀) — 가장 오래된
        # 항목부터 버리는 경계 있는 캐시로, 무제한 메모리 증가를 막는다.
        self._seen_keys: OrderedDict[str, None] = OrderedDict()

    def handle(self, payload: Mapping[str, Any], *, idempotency_key: str) -> bool:
        """수신 payload 하나를 처리한다.

        반환값: 실제로 새로 처리했으면 True, 이미 처리한 idempotency_key라
        무시했으면 False. 파싱 실패는 `EntryEventIntakeError`를 던진다(멱등키
        중복 여부와 무관하게 매번 검증한다).
        """

        if idempotency_key in self._seen_keys:
            return False
        incoming = IncomingEntryEvent.from_payload(payload)
        self._monitor.add_entry_event(incoming.to_entry_event())
        self._remember(idempotency_key)
        return True

    def _remember(self, idempotency_key: str) -> None:
        self._seen_keys[idempotency_key] = None
        if len(self._seen_keys) > self._max_remembered_keys:
            self._seen_keys.popitem(last=False)

"""OCR-트랙 매칭 결과(입차 판정)를 백엔드 `POST /hw/parking/entry`로 전송한다(383번).

`jetson_vehicle_tracking_baseline.py`의 `_try_match_entry_event`가 로컬에서
"이 OCR 번호판이 어느 track_id의 차인지"를 매칭한 뒤, 그 결과(track_id +
plate_number + 매칭에 쓰인 EntryEvent.captured_at)를 이 클래스로 백엔드에
보고한다. 등록 차량 여부 판정(ALLOW/REVIEW/DENY)과 `ParkingSession` 생성은
백엔드가 담당하므로(편집거리 기반 매칭), 이 파일은 그 결과를 그대로
전달하고 응답을 파싱하는 것까지만 담당한다.

**CLI 연결 시 주의**: `HttpResultPublisher`와 마찬가지로 `report_entry()`는
네트워크 실패 시 `EntryReportError`를 던진다. 트래킹 루프에 연결할 때는
이 예외를 잡아서 로그만 남기고 계속 진행하도록 감싸야 한다(연결 자체는
별도 커밋).

멱등성(Idempotency-Key): 백엔드가 같은 물리적 입차 이벤트의 재전송(네트워크
재시도 등)을 중복 세션 생성 없이 처리할 수 있도록, 매 호출마다 새로 만드는
값이 아니라 `track_id`+`plate_number`+`entry_time`으로 결정적으로 계산한다
— 같은 이벤트를 재시도하면 항상 같은 키가 나와야 하고, 다른 이벤트는 달라야
한다. `parking_sessions.idempotency_key`는 `VARCHAR(100)` + UNIQUE 제약이며,
SHA-256 hex(64자)는 여유 있게 들어간다.

`entry_time`은 반드시 timezone-aware여야 한다(리뷰 반영, 명시적으로 검증함)
— naive datetime을 넘기면 `isoformat()`에 UTC 오프셋이 안 붙어서, 백엔드의
`OffsetDateTime` 역직렬화가 한참 뒤(HTTP 응답 단계)에야 실패해 원인 추적이
어려워진다. `report_entry()`가 호출 시점에 바로 `ValueError`를 던진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

LOGGER = logging.getLogger("http_entry_reporter")

ENTRY_PATH = "/hw/parking/entry"


class EntryReportError(RuntimeError):
    """입차 판정 보고 요청이 실패한 경우."""


@dataclass(frozen=True, slots=True)
class EntryReportResult:
    """백엔드 `HwEntryResponse`를 그대로 옮긴 결과.

    `access_decision`은 "ALLOW"/"REVIEW"/"DENY" 중 하나다. DENY는 예외가
    아니라 정상적인 판정 결과이므로(등록되지 않은 차량 등), 호출자가
    `access_decision`을 보고 직접 분기해야 한다.
    """

    access_decision: str
    registered: bool
    vehicle_id: int | None
    is_disabled_vehicle: bool | None
    is_electric: bool | None
    vehicle_status: str | None
    tracking_id: str
    session_id: int | None
    duplicate_request: bool


def _idempotency_key(track_id: int, plate_number: str, entry_time: datetime) -> str:
    """같은 입차 이벤트를 재전송해도 항상 같은 값이 나오는 결정적 키를 만든다."""

    digest = hashlib.sha256()
    digest.update(str(track_id).encode("utf-8"))
    digest.update(b"|")
    digest.update(plate_number.encode("utf-8"))
    digest.update(b"|")
    digest.update(entry_time.isoformat().encode("utf-8"))
    return digest.hexdigest()


class HttpEntryReporter:
    """OCR-트랙 매칭 결과를 백엔드 `POST /hw/parking/entry`로 전송한다."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def report_entry(
        self,
        *,
        track_id: int,
        plate_number: str,
        entry_time: datetime,
        ocr_confidence: float | None = None,
    ) -> EntryReportResult:
        """입차 판정 한 건을 백엔드로 전송하고 파싱된 결과를 반환한다.

        실패하면 `EntryReportError`를 던진다. DENY/REVIEW는 실패가 아니라
        정상 응답이므로 예외로 처리하지 않는다.

        `entry_time`이 naive datetime(tzinfo 없음)이면 `ValueError`를 던진다
        (리뷰 반영) — 조용히 오프셋 없는 문자열을 보내면 백엔드
        `OffsetDateTime` 역직렬화가 나중에야 실패해 원인 추적이 어려워지므로,
        여기서 바로 막는다.
        """

        if entry_time.tzinfo is None:
            raise ValueError("entry_time은 timezone-aware datetime이어야 합니다(naive datetime 불가).")

        payload: dict[str, Any] = {
            "trackingId": str(track_id),
            "recognizedPlateNumber": plate_number,
            "ocrConfidence": ocr_confidence,
            "entryTime": entry_time.isoformat(),
        }
        idempotency_key = _idempotency_key(track_id, plate_number, entry_time)
        return self._post(payload, idempotency_key)

    def _post(self, payload: dict[str, Any], idempotency_key: str) -> EntryReportResult:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            f"{self._base_url}{ENTRY_PATH}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-HW-API-Key": self._api_key,
                "Idempotency-Key": idempotency_key,
            },
        )
        try:
            with urllib_request.urlopen(req, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", 200)
                raw = response.read()
        except HTTPError as exc:
            raise EntryReportError(f"백엔드 요청이 거부됐습니다(HTTP {exc.code}): {exc.reason}") from exc
        except URLError as exc:
            raise EntryReportError(f"백엔드({self._base_url})에 연결할 수 없습니다: {exc.reason}") from exc
        except TimeoutError as exc:
            # (리뷰 반영) socket.timeout(3.10+에서 TimeoutError의 별칭)은 URLError의
            # 하위 클래스가 아니라서 위 `except URLError`가 못 잡는다 — urllib이 연결
            # 단계의 OSError는 URLError로 감싸지만, 응답 대기 중 타임아웃은 감싸지지
            # 않고 그대로 새어나올 수 있어 별도로 잡아야 한다(재현 확인됨).
            raise EntryReportError(f"백엔드({self._base_url}) 응답 대기 중 타임아웃이 발생했습니다: {exc}") from exc

        if status >= 300:
            raise EntryReportError(f"백엔드가 실패 응답을 반환했습니다: HTTP {status}")

        try:
            envelope = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise EntryReportError(f"백엔드 응답을 JSON으로 해석할 수 없습니다: {exc}") from exc

        if not envelope.get("isSuccess", False):
            raise EntryReportError(
                f"백엔드가 실패로 응답했습니다: {envelope.get('message', '(메시지 없음)')}"
            )

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise EntryReportError("백엔드 응답에 result가 없습니다.")

        # (리뷰 대응 중 자체 발견) 필수 필드가 빠진 손상된 응답이면 raw KeyError
        # 대신 EntryReportError로 감싼다 — naive datetime/timeout과 같은 이유로,
        # 이 클래스가 던지는 예외 타입은 항상 EntryReportError로 일관돼야 한다.
        try:
            return EntryReportResult(
                access_decision=result["accessDecision"],
                registered=result["registered"],
                vehicle_id=result.get("vehicleId"),
                is_disabled_vehicle=result.get("isDisabledVehicle"),
                is_electric=result.get("isElectric"),
                vehicle_status=result.get("vehicleStatus"),
                tracking_id=result["trackingId"],
                session_id=result.get("sessionId"),
                duplicate_request=result["duplicateRequest"],
            )
        except KeyError as exc:
            raise EntryReportError(f"백엔드 응답에 필수 필드가 없습니다: {exc}") from exc

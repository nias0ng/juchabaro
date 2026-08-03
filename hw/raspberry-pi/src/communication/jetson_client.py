"""Jetson 입차 이벤트 API 클라이언트."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from src.communication.schemas import (
    EntryMatchOutcome,
    JetsonEntryAcceptance,
    JetsonEntryRequest,
)


class JetsonClientError(RuntimeError):
    """Jetson 요청에 실패했을 때 발생한다."""


def _json_bytes(payload: dict[str, object]) -> bytes:
    """재시도마다 같은 요청 bytes를 만들도록 JSON을 안정적으로 직렬화한다."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class JetsonClient:
    ENTRY_PATH = "/internal/entry-events"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._entry_url = f"{base_url.rstrip('/')}{self.ENTRY_PATH}"
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def send_entry(
        self,
        request: JetsonEntryRequest,
        *,
        idempotency_key: str,
    ) -> JetsonEntryAcceptance:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")

        http_request = Request(
            self._entry_url,
            data=_json_bytes(request.to_payload()),
            headers={
                "X-Internal-API-Key": self._api_key,
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            method="POST",
        )

        try:
            with urlopen(
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                status = response.getcode()
                body = response.read()
        except HTTPError as error:
            raise JetsonClientError(
                f"Jetson이 HTTP {error.code}으로 응답했습니다."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise JetsonClientError(
                "Jetson에 연결하지 못했습니다."
            ) from error

        if status != 202:
            raise JetsonClientError(
                f"Jetson이 HTTP {status}으로 응답했습니다."
            )

        result = self._parse_result(body, "EntryDecision 접수")
        try:
            acceptance = JetsonEntryAcceptance.from_payload(result)
        except (KeyError, TypeError, ValueError) as error:
            raise JetsonClientError(
                "Jetson EntryDecision 접수 결과 형식이 올바르지 않습니다."
            ) from error

        if (
            acceptance.entry_attempt_id != request.entry_attempt_id
            or acceptance.decision_revision != request.decision_revision
        ):
            raise JetsonClientError(
                "Jetson 접수 결과의 identity 또는 revision이 요청과 다릅니다."
            )
        return acceptance

    def get_entry_match_outcome(
        self,
        entry_attempt_id: str,
    ) -> EntryMatchOutcome:
        """API 3에서 입차 시도와 PhysicalVehicle의 매칭 상태를 조회한다."""

        try:
            UUID(entry_attempt_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("entry_attempt_id는 UUID 문자열이어야 합니다.") from error

        http_request = Request(
            f"{self._entry_url}/{quote(entry_attempt_id, safe='')}",
            headers={"X-Internal-API-Key": self._api_key},
            method="GET",
        )

        try:
            with urlopen(
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                status = response.getcode()
                body = response.read()
        except HTTPError as error:
            raise JetsonClientError(
                f"Jetson이 HTTP {error.code}으로 응답했습니다."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise JetsonClientError("Jetson에 연결하지 못했습니다.") from error

        if status != 200:
            raise JetsonClientError(
                f"Jetson이 HTTP {status}으로 응답했습니다."
            )

        result = self._parse_result(body, "EntryMatchOutcome 조회")
        try:
            outcome = EntryMatchOutcome.from_payload(result)
        except (KeyError, TypeError, ValueError) as error:
            raise JetsonClientError(
                "Jetson EntryMatchOutcome 형식이 올바르지 않습니다."
            ) from error

        if outcome.entry_attempt_id != entry_attempt_id:
            raise JetsonClientError(
                "Jetson 조회 결과의 entryAttemptId가 요청과 다릅니다."
            )
        return outcome

    @staticmethod
    def _parse_result(body: bytes, operation: str) -> dict[str, Any]:
        try:
            envelope: Any = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise JetsonClientError(
                f"Jetson {operation} 응답이 올바른 JSON이 아닙니다."
            ) from error

        if not isinstance(envelope, dict):
            raise JetsonClientError(
                f"Jetson {operation} 응답 형식이 올바르지 않습니다."
            )
        if envelope.get("isSuccess") is not True:
            message = envelope.get("message")
            if not isinstance(message, str):
                message = f"Jetson {operation}에 실패했습니다."
            raise JetsonClientError(message)

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise JetsonClientError(
                f"Jetson {operation} 응답에 result가 없습니다."
            )
        return result

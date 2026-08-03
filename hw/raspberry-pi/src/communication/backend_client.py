"""Backend 입차 판정 API 클라이언트."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.communication.schemas import BackendEntryRequest, BackendEntryResult


class BackendClientError(RuntimeError):
    """Backend 요청 또는 응답 처리에 실패했을 때 발생한다."""


def _json_bytes(payload: dict[str, object]) -> bytes:
    """재시도마다 같은 요청 bytes를 만들도록 JSON을 안정적으로 직렬화한다."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class BackendClient:
    ENTRY_PATH = "/hw/parking/entry"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._entry_url = f"{base_url.rstrip('/')}{self.ENTRY_PATH}"
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def request_entry(
        self,
        request: BackendEntryRequest,
        *,
        idempotency_key: str,
    ) -> BackendEntryResult:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")

        http_request = Request(
            self._entry_url,
            data=_json_bytes(request.to_payload()),
            headers={
                "X-HW-API-Key": self._api_key,
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
            raise BackendClientError(
                f"Backend가 HTTP {error.code}으로 응답했습니다."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise BackendClientError(
                "Backend에 연결하지 못했습니다."
            ) from error

        if status not in (200, 201):
            raise BackendClientError(
                f"Backend가 HTTP {status}으로 응답했습니다."
            )

        result = self._parse_result(body)
        if result.entry_attempt_id != request.entry_attempt_id:
            raise BackendClientError(
                "Backend 응답의 entryAttemptId가 요청과 다릅니다."
            )
        return result

    @staticmethod
    def _parse_result(body: bytes) -> BackendEntryResult:
        try:
            envelope: Any = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise BackendClientError(
                "Backend 응답이 올바른 JSON이 아닙니다."
            ) from error

        if not isinstance(envelope, dict):
            raise BackendClientError("Backend 응답 형식이 올바르지 않습니다.")

        if envelope.get("isSuccess") is not True:
            message = envelope.get("message")
            if not isinstance(message, str):
                message = "Backend가 요청 처리에 실패했습니다."
            raise BackendClientError(message)

        result = envelope.get("result")
        if not isinstance(result, dict):
            raise BackendClientError(
                "Backend 응답에 result가 없습니다."
            )

        try:
            return BackendEntryResult.from_payload(result)
        except (KeyError, TypeError, ValueError) as error:
            raise BackendClientError(
                "Backend result 형식이 올바르지 않습니다."
            ) from error

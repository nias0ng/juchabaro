"""Jetson 입차 이벤트 API 클라이언트."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.communication.schemas import JetsonEntryRequest


class JetsonClientError(RuntimeError):
    """Jetson 요청에 실패했을 때 발생한다."""


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
    ) -> None:
        http_request = Request(
            self._entry_url,
            data=json.dumps(
                request.to_payload(),
                ensure_ascii=False,
            ).encode("utf-8"),
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
        except HTTPError as error:
            raise JetsonClientError(
                f"Jetson이 HTTP {error.code}으로 응답했습니다."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise JetsonClientError(
                "Jetson에 연결하지 못했습니다."
            ) from error

        if not 200 <= status < 300:
            raise JetsonClientError(
                f"Jetson이 HTTP {status}으로 응답했습니다."
            )

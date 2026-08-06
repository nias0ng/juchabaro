"""GET /live/stream의 MJPEG 계약과 비활성 경계 테스트.

`/live/stream`은 새 프레임이 없으면 끝나지 않는 무한 스트림이다. 이 저장소에
설치된 starlette(1.3.1)의 `TestClient`는 ASGI 앱 호출 전체가 끝나야만
응답을 반환한다 — `client.stream(...)`으로도 body를 조금씩 흘려받을 수
없고, 앱 코루틴이 return할 때까지 호출 자체가 block된다. 그리고 이
`TestClient`의 `Request.is_disconnected()`는 내부적으로 이미 취소된
`anyio.CancelScope`로 `receive()`를 감싸 넘어가므로, 클라이언트가
`with` 블록을 빠져나가도 실제 "http.disconnect" 메시지가 전달되지 않아
`True`가 되는 일이 없다(직접 실험으로 확인함). 그 결과 무한 generator를
`client.stream(...)` + 조기 종료로 테스트하면 항상 hang한다.

그래서 `test_stream_serves_multipart_with_the_latest_jpeg`는 ASGI
callable(`application`)을 직접 호출해, 원하는 바이트가 응답 본문에
나타나면 `send()`가 `asyncio.CancelledError`를 던지게 해 실제 클라이언트
연결 종료를 흉내낸다. `CancelledError`는 `BaseException`이라 `register_
error_handlers`가 등록한 `except Exception` 계열 handler들을 건드리지
않고 `create_collapsing_task_group`의 취소 경로로 조용히 정리된다 — 이
방식으로 실제 라우터 wiring(상태 코드, 헤더, multipart 바디)을 그대로
검증하면서도 무한 대기를 피한다. 나머지 두 테스트는 스트리밍 body를 읽지
않으므로 평범한 `TestClient`로 충분하다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.error_handlers import register_error_handlers
from src.api.live_stream_router import router


class _StubPublisher:
    def __init__(self, jpeg_bytes: bytes | None) -> None:
        self._jpeg_bytes = jpeg_bytes

    def latest_jpeg(self) -> bytes | None:
        return self._jpeg_bytes


def _build_app(publisher: object | None) -> FastAPI:
    application = FastAPI()
    register_error_handlers(application)
    application.include_router(router)
    application.state.overlay_publisher = publisher
    return application


def _client(publisher: object | None) -> TestClient:
    return TestClient(_build_app(publisher))


async def _drive_until_disconnect(
    application: FastAPI,
    path: str,
    needle: bytes,
    *,
    timeout_seconds: float = 5.0,
) -> tuple[dict[str, Any], bytes]:
    """ASGI 앱을 직접 호출해, `needle`이 응답 본문에 나타나면 클라이언트가
    연결을 끊은 것처럼 `send()`에서 `CancelledError`를 던진다.

    `timeout_seconds`는 `needle`을 못 찾았을 때 테스트가 조용히 무한 대기에
    빠지는 대신 명확한 실패로 끝나게 하는 안전망이다. `receive()`에
    `asyncio.sleep(0)` checkpoint가 반드시 있어야 한다 — 없으면
    `StreamingResponse`가 나란히 띄우는 `listen_for_disconnect(receive)`
    루프가 event loop에 제어를 돌려주지 않는 busy loop가 되어, 위
    `timeout_seconds`조차 발동하지 못하고 프로세스 전체가 멈춘다.
    """

    status: dict[str, Any] = {}
    collected = bytearray()

    async def receive() -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            status["status_code"] = message["status"]
            status["headers"] = message.get("headers", [])
        elif message["type"] == "http.response.body":
            collected.extend(message.get("body", b""))
            if needle in collected:
                raise asyncio.CancelledError()

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("test", 1),
        "server": ("test", 80),
        "root_path": "",
    }

    try:
        await asyncio.wait_for(
            application(scope, receive, send), timeout=timeout_seconds
        )
    except asyncio.CancelledError:
        pass

    return status, bytes(collected)


def test_stream_serves_multipart_with_the_latest_jpeg() -> None:
    application = _build_app(_StubPublisher(b"\xff\xd8fake-jpeg-payload"))

    status, body = asyncio.run(
        _drive_until_disconnect(
            application, "/live/stream", b"fake-jpeg-payload"
        )
    )

    assert status["status_code"] == 200
    content_type = dict(status["headers"])[b"content-type"]
    assert content_type.startswith(b"multipart/x-mixed-replace")
    assert b"Content-Type: image/jpeg" in body
    assert b"--jetsonframe" in body


def test_stream_is_unavailable_when_publisher_is_not_configured() -> None:
    response = _client(None).get("/live/stream")

    assert response.status_code == 503
    assert response.json()["result"]["errorType"] == "LIVE_STREAM_DISABLED"


def test_viewer_page_embeds_the_stream_url() -> None:
    response = _client(_StubPublisher(b"\xff\xd8x")).get("/live")

    assert response.status_code == 200
    assert "/live/stream" in response.text

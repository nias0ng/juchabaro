"""데모용 라이브 오버레이 MJPEG 스트리밍 엔드포인트.

`OverlayPublisher`가 게시한 최신 JPEG 한 장을 `multipart/x-mixed-replace`로
계속 내보낸다. 각 응답은 공유 버퍼를 읽기만 하므로 시청자가 늘어도 카메라
캡처와 추론은 그대로 한 번만 돈다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.api.error_handlers import JetsonApiError

router = APIRouter(tags=["Live"])

BOUNDARY = "jetsonframe"
MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={BOUNDARY}"
_POLL_INTERVAL_SECONDS = 1.0 / 30.0

_VIEWER_PAGE = (
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<title>Jetson Live Overlay</title>"
    "<style>html,body{margin:0;background:#000}"
    "img{width:100vw;height:100vh;object-fit:contain}</style>"
    "</head><body><img src=\"/live/stream\" alt=\"live overlay\"></body></html>"
)


class OverlayFrameSource(Protocol):
    """라우터가 오버레이 게시자에게 요구하는 최소 계약."""

    def latest_jpeg(self) -> bytes | None:
        ...


def _require_publisher(request: Request) -> OverlayFrameSource:
    publisher = getattr(request.app.state, "overlay_publisher", None)
    if publisher is None:
        raise JetsonApiError(
            status_code=503,
            error_type="LIVE_STREAM_DISABLED",
            message="라이브 오버레이 스트리밍이 꺼져 있습니다.",
            retryable=False,
        )
    return publisher


def _multipart_part(jpeg_bytes: bytes) -> bytes:
    return b"".join(
        (
            b"--",
            BOUNDARY.encode("ascii"),
            b"\r\nContent-Type: image/jpeg\r\nContent-Length: ",
            str(len(jpeg_bytes)).encode("ascii"),
            b"\r\n\r\n",
            jpeg_bytes,
            b"\r\n",
        )
    )


async def _stream_frames(
    publisher: OverlayFrameSource, request: Request
) -> AsyncIterator[bytes]:
    """같은 프레임을 두 번 보내지 않고, 새 프레임이 올 때만 내보낸다."""

    last_sent: bytes | None = None
    while not await request.is_disconnected():
        jpeg_bytes = publisher.latest_jpeg()
        if jpeg_bytes is not None and jpeg_bytes is not last_sent:
            last_sent = jpeg_bytes
            yield _multipart_part(jpeg_bytes)
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


@router.get("/live", response_class=HTMLResponse)
def live_viewer_page() -> HTMLResponse:
    """OBS 브라우저 소스가 잡을 `<img>` 한 장짜리 페이지."""

    return HTMLResponse(_VIEWER_PAGE)


@router.get("/live/stream")
def live_stream(request: Request) -> StreamingResponse:
    """최신 오버레이 프레임을 MJPEG로 계속 내보낸다."""

    publisher = _require_publisher(request)
    return StreamingResponse(_stream_frames(publisher, request), media_type=MEDIA_TYPE)

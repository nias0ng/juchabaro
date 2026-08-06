"""라이브 오버레이 발행에 공통으로 쓰는 단일 슬롯 버퍼와 안내 프레임.

`LiveStreamLoop`(자체 캡처 루프를 가진 개발용 도구)와 `OverlayPublisher`(운영
`MonitoringWorker`에 붙는 frame_observer)가 같은 구현을 쓰도록 여기로 모았다.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.live.live_overlay_renderer import encode_jpeg, render_overlay_jpeg
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import TrackingBatch

DEFAULT_TARGET_FPS = 15.0
PLACEHOLDER_HEIGHT = 480
PLACEHOLDER_WIDTH = 640

RenderFn = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], bytes]


class LatestFrameBuffer:
    """가장 최근 JPEG 프레임 한 장만 담는 스레드 세이프 단일 슬롯 버퍼."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: bytes | None = None

    def publish(self, jpeg_bytes: bytes) -> None:
        with self._lock:
            self._latest = jpeg_bytes

    def get_latest(self) -> bytes | None:
        with self._lock:
            return self._latest


def placeholder_jpeg(message: str) -> bytes:
    """판정 프레임이 없을 때 보여줄 안내 프레임.

    `cv2.putText`는 OpenCV Hershey 폰트를 사용해 ASCII만 그릴 수 있다 — 반드시
    영문 메시지만 넘겨야 한다.
    """

    canvas = np.zeros((PLACEHOLDER_HEIGHT, PLACEHOLDER_WIDTH, 3), dtype=np.uint8)
    cv2.putText(
        canvas, message, (24, PLACEHOLDER_HEIGHT // 2),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
    )
    return encode_jpeg(canvas)


def build_default_render(zones: ZoneRegistry, jpeg_quality: int) -> RenderFn:
    """`zones`/`jpeg_quality`를 고정한 `render_overlay_jpeg` 클로저를 반환한다.

    `LiveStreamLoop`와 `OverlayPublisher` 둘 다 `render`를 직접 넘기지 않았을 때
    쓰는 기본 렌더 함수라 여기로 모았다.
    """

    def render(
        frame: CapturedFrame, tracking_batch: TrackingBatch, result: FrameObservationResult
    ) -> bytes:
        return render_overlay_jpeg(
            frame, tracking_batch, result, zones=zones, jpeg_quality=jpeg_quality
        )

    return render

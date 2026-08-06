"""운영 MonitoringWorker에 붙어 오버레이 JPEG를 게시하는 FrameObserver.

`LiveStreamLoop`와 달리 자체 캡처 루프를 갖지 않는다 — 이미 돌고 있는
`MonitoringPipeline` 루프가 매 프레임 이 객체를 호출한다. 그래서 두 가지
제약이 있다.

1. 렌더링·인코딩 예외를 여기서 전부 삼킨다. `MonitoringPipeline`으로
   전파되면 `MonitoringWorker`가 치명 오류로 처리해 카메라·모델을 닫는다.
2. 프레임레이트 제한을 sleep이 아니라 **드롭**으로 한다. 이 콜백은 판정
   루프와 같은 스레드에서 돌기 때문에, 여기서 기다리면 판정 자체가 느려진다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.live.frame_publishing import (
    DEFAULT_TARGET_FPS,
    LatestFrameBuffer,
    RenderFn,
    build_default_render,
    placeholder_jpeg,
)
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import TrackingBatch

LOGGER = logging.getLogger(__name__)

MonotonicFn = Callable[[], float]


class OverlayPublisher:
    """오버레이 JPEG를 단일 슬롯 버퍼에 게시하는 `FrameObserver` 구현체."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry | None = None,
        jpeg_quality: int = 80,
        target_fps: float = DEFAULT_TARGET_FPS,
        render: RenderFn | None = None,
        monotonic: MonotonicFn = time.monotonic,
    ) -> None:
        if render is None and zones is None:
            raise ValueError("zones 또는 render 중 하나는 반드시 지정해야 합니다")
        if target_fps <= 0:
            raise ValueError("target_fps는 0보다 커야 합니다")
        self._render: RenderFn = render or build_default_render(zones, jpeg_quality)
        self._min_interval_seconds = 1.0 / target_fps
        self._monotonic = monotonic
        self._buffer = LatestFrameBuffer()
        self._last_published_at: float | None = None
        self._render_error_placeholder_jpeg = placeholder_jpeg("RENDER ERROR")

    def latest_jpeg(self) -> bytes | None:
        """가장 최근 게시된 오버레이 JPEG. 아직 프레임이 없으면 None."""

        return self._buffer.get_latest()

    def __call__(
        self,
        frame: CapturedFrame,
        tracking_batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        now = self._monotonic()
        if (
            self._last_published_at is not None
            and now - self._last_published_at < self._min_interval_seconds
        ):
            return
        self._last_published_at = now
        try:
            jpeg_bytes = self._render(frame, tracking_batch, result)
        except Exception:
            LOGGER.exception("오버레이 렌더링에 실패해 placeholder로 대체합니다.")
            jpeg_bytes = self._render_error_placeholder_jpeg
        self._buffer.publish(jpeg_bytes)

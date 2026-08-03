"""MonitoringPipeline을 백그라운드 스레드에서 돌리며 오버레이 JPEG를 게시한다.

`MonitoringWorker`(`src/application/monitoring_worker.py`)를 재사용하지 않는다 —
카메라 재연결 백오프, 프레임레이트 캡 같은 데모 전용 정책이 있어
`scripts/replay_pilot_video.py`처럼
`MonitoringPipeline.process_next_frame()`을 직접 호출하는 자체 루프가 필요하다.
리허설 영상이 끝나면(`EndOfVideo`) 반복재생하지 않고 정지 안내 프레임을 게시한
채 루프가 스스로 끝난다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Event, Lock, Thread

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.camera.models import CapturedFrame
from src.live.live_overlay_renderer import encode_jpeg, render_overlay_jpeg
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import TrackingBatch

LOGGER = logging.getLogger(__name__)

_TARGET_FPS = 15.0
_RECONNECT_BACKOFF_SECONDS = 2.0
_PLACEHOLDER_HEIGHT = 480
_PLACEHOLDER_WIDTH = 640

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


def _throttle_sleep_seconds(elapsed_seconds: float, *, target_fps: float = _TARGET_FPS) -> float:
    """목표 fps 간격보다 빨리 처리됐으면 나머지 대기 시간을, 아니면 0을 반환한다.

    소스의 실제 fps를 조회하지 않는다 — 리허설 영상처럼 원본이 이미 이 값보다
    느리면 `elapsed_seconds`가 목표 간격을 넘어서 자연히 0을 반환한다.
    """

    target_interval = 1.0 / target_fps
    remaining = target_interval - elapsed_seconds
    return remaining if remaining > 0.0 else 0.0


def _placeholder_jpeg(message: str) -> bytes:
    """카메라 재연결 대기·리허설 종료 등 판정 프레임이 없을 때 보여줄 안내 프레임.

    `cv2.putText`는 OpenCV Hershey 폰트를 사용해 ASCII만 그릴 수 있다 — 반드시
    영문 메시지만 넘겨야 한다.
    """

    canvas = np.zeros((_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3), dtype=np.uint8)
    cv2.putText(
        canvas, message, (24, _PLACEHOLDER_HEIGHT // 2),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
    )
    return encode_jpeg(canvas)


class LiveStreamLoop:
    """`MonitoringPipeline`을 백그라운드 스레드에서 돌리며 오버레이 JPEG를 게시한다.

    `render`(기본값: 478의 `render_overlay_jpeg`에 `zones`/`jpeg_quality`를 고정한
    클로저)의 예외는 이 클래스가 잡아 placeholder로 대체한다 — `encode_jpeg`
    docstring과 같은 이유로 `MonitoringPipeline`에 전파돼서는 안 된다.
    """

    def __init__(
        self,
        pipeline: MonitoringPipeline,
        *,
        zones: ZoneRegistry | None = None,
        jpeg_quality: int = 80,
        reconnect_backoff_seconds: float = _RECONNECT_BACKOFF_SECONDS,
        target_fps: float = _TARGET_FPS,
        render: RenderFn | None = None,
    ) -> None:
        if render is None and zones is None:
            raise ValueError("zones 또는 render 중 하나는 반드시 지정해야 합니다")
        if target_fps <= 0:
            raise ValueError("target_fps는 0보다 커야 합니다")
        if reconnect_backoff_seconds < 0:
            raise ValueError("reconnect_backoff_seconds는 음수일 수 없습니다")
        self._pipeline = pipeline
        self._reconnect_backoff_seconds = reconnect_backoff_seconds
        self._target_fps = target_fps
        self._render: RenderFn = render or (
            lambda frame, tracking_batch, result: render_overlay_jpeg(
                frame, tracking_batch, result, zones=zones, jpeg_quality=jpeg_quality
            )
        )
        self._buffer = LatestFrameBuffer()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._failure: Exception | None = None
        self._reconnecting_placeholder_jpeg = _placeholder_jpeg("CAMERA DISCONNECTED - RECONNECTING")
        self._video_ended_placeholder_jpeg = _placeholder_jpeg("VIDEO ENDED")
        self._render_error_placeholder_jpeg = _placeholder_jpeg("RENDER ERROR")

    @property
    def failure(self) -> Exception | None:
        """Background loop가 예기치 않게 종료된 원인을 반환한다."""

        return self._failure

    @property
    def is_running(self) -> bool:
        """Loop thread가 현재 실행 중인지 반환한다."""

        return self._thread is not None and self._thread.is_alive()

    def latest_jpeg(self) -> bytes | None:
        """가장 최근 게시된 오버레이 JPEG. 아직 프레임이 없으면 None."""

        return self._buffer.get_latest()

    def start(self) -> None:
        """Pipeline을 열고 loop thread를 시작한다."""

        if self._thread is not None:
            raise RuntimeError("live stream loop may only be started once")

        self._pipeline.open()
        thread = Thread(target=self._run, name="jetson-live-stream", daemon=False)
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self._pipeline.close()
            raise

    def stop(self) -> None:
        """신규 frame 처리를 멈추고 자원 정리까지 기다린다."""

        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        try:
            self._loop()
        except Exception as error:
            self._failure = error
            LOGGER.exception("라이브 스트림 루프가 종료됐습니다.")
        finally:
            try:
                self._pipeline.close()
            except Exception as error:
                if self._failure is None:
                    self._failure = error
                LOGGER.exception("라이브 스트림 자원 정리에 실패했습니다.")

    def _loop(self) -> None:
        while not self._stop_requested.is_set():
            started_at = time.monotonic()
            try:
                if not self._process_one_frame():
                    return
            finally:
                elapsed = time.monotonic() - started_at
                wait_seconds = _throttle_sleep_seconds(elapsed, target_fps=self._target_fps)
                if wait_seconds > 0.0:
                    self._stop_requested.wait(wait_seconds)

    def _process_one_frame(self) -> bool:
        """한 프레임을 처리한다.

        Returns: 루프를 계속해야 하면 True, 끝내야 하면 False(리허설 영상 종료).
        """

        try:
            self._pipeline.process_next_frame(frame_observer=self._on_frame)
        except EndOfVideo:
            LOGGER.info("리허설 영상이 끝나 루프를 종료합니다.")
            self._buffer.publish(self._video_ended_placeholder_jpeg)
            return False
        except FrameSourceError as error:
            LOGGER.warning("카메라 연결이 끊겼습니다: %s", error)
            self._buffer.publish(self._reconnecting_placeholder_jpeg)
            self._reconnect()
        return True

    def _reconnect(self) -> None:
        """`stop()`이 호출되거나 재연결에 성공할 때까지 백오프하며 재시도한다."""

        while not self._stop_requested.is_set():
            self._stop_requested.wait(self._reconnect_backoff_seconds)
            if self._stop_requested.is_set():
                return
            try:
                self._pipeline.close()
                self._pipeline.open()
                return
            except Exception as error:
                LOGGER.warning("재연결 실패, 다시 시도합니다: %s", error)

    def _on_frame(
        self,
        frame: CapturedFrame,
        tracking_batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        try:
            jpeg_bytes = self._render(frame, tracking_batch, result)
        except Exception:
            LOGGER.exception("오버레이 렌더링에 실패해 placeholder로 대체합니다.")
            jpeg_bytes = self._render_error_placeholder_jpeg
        self._buffer.publish(jpeg_bytes)

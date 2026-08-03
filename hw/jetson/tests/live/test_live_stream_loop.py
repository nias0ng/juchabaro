"""LiveStreamLoop과 지원 유닛(버퍼·throttle·placeholder)의 스레드 생명주기 테스트."""

from __future__ import annotations

from threading import Event

import cv2
import numpy as np
import pytest

from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.live.live_stream_loop import (
    LatestFrameBuffer,
    _placeholder_jpeg,
    _throttle_sleep_seconds,
    _PLACEHOLDER_HEIGHT,
    _PLACEHOLDER_WIDTH,
)


def test_latest_frame_buffer_starts_empty_and_overwrites() -> None:
    buffer = LatestFrameBuffer()

    assert buffer.get_latest() is None

    buffer.publish(b"first")
    assert buffer.get_latest() == b"first"

    buffer.publish(b"second")
    assert buffer.get_latest() == b"second"


def test_throttle_sleep_seconds_returns_remaining_interval_when_faster_than_target() -> None:
    # target_fps=15 -> 목표 간격 1/15초 ~= 0.0667초. 0.02초 만에 끝났으면 나머지를 재운다.
    remaining = _throttle_sleep_seconds(0.02, target_fps=15.0)

    assert remaining == pytest.approx(1.0 / 15.0 - 0.02)


def test_throttle_sleep_seconds_returns_zero_when_slower_than_target() -> None:
    # 원본 소스가 이미 목표보다 느리면(예: 5fps 리허설 영상) sleep을 추가하지 않는다.
    remaining = _throttle_sleep_seconds(1.0, target_fps=15.0)

    assert remaining == 0.0


def test_placeholder_jpeg_returns_decodable_bytes() -> None:
    jpeg_bytes = _placeholder_jpeg("카메라 연결 끊김")

    assert isinstance(jpeg_bytes, bytes)
    assert len(jpeg_bytes) > 0
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3)


class _FramePipeline:
    """process_next_frame이 호출될 때마다 frame_observer를 실행하는 가짜 파이프라인."""

    def __init__(self, *, fail_times: int = 0, eov_times: int = 0) -> None:
        self.open_count = 0
        self.close_count = 0
        self.calls = 0
        self.processed = Event()
        self.closed = Event()
        self._fail_times = fail_times
        self._eov_times = eov_times

    def open(self) -> None:
        self.open_count += 1

    def process_next_frame(self, *, frame_observer=None):
        self.calls += 1
        if self.calls <= self._eov_times:
            raise EndOfVideo("video exhausted")
        if self.calls <= self._eov_times + self._fail_times:
            raise FrameSourceError("camera disconnected")
        if frame_observer is not None:
            frame_observer(object(), object(), object())
        self.processed.set()
        return object()

    def close(self) -> None:
        self.close_count += 1
        self.closed.set()


def test_live_stream_loop_requires_zones_or_render() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    with pytest.raises(ValueError, match="zones.*render|render.*zones"):
        LiveStreamLoop(_FramePipeline())


def test_live_stream_loop_publishes_rendered_frames_and_stops_cleanly() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    pipeline = _FramePipeline()
    rendered = []

    def fake_render(frame, tracking_batch, result) -> bytes:
        rendered.append((frame, tracking_batch, result))
        return b"rendered-jpeg"

    loop = LiveStreamLoop(pipeline, render=fake_render, target_fps=1000.0)

    loop.start()
    assert pipeline.processed.wait(timeout=1.0)
    loop.stop()

    assert pipeline.open_count == 1
    assert pipeline.close_count == 1
    assert loop.is_running is False
    assert loop.failure is None
    assert loop.latest_jpeg() == b"rendered-jpeg"
    assert len(rendered) >= 1


def test_live_stream_loop_falls_back_to_placeholder_when_render_fails() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    pipeline = _FramePipeline()

    def failing_render(frame, tracking_batch, result) -> bytes:
        raise ValueError("boom")

    loop = LiveStreamLoop(pipeline, render=failing_render, target_fps=1000.0)

    loop.start()
    assert pipeline.processed.wait(timeout=1.0)
    loop.stop()

    assert loop.failure is None
    jpeg_bytes = loop.latest_jpeg()
    assert jpeg_bytes is not None
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3)


def test_live_stream_loop_reconnects_after_frame_source_error() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    pipeline = _FramePipeline(fail_times=1)
    recovered = Event()
    original_process = pipeline.process_next_frame

    def process_next_frame(*, frame_observer=None):
        result = original_process(frame_observer=frame_observer)
        if pipeline.calls == pipeline._fail_times + 1:
            recovered.set()
        return result

    pipeline.process_next_frame = process_next_frame  # type: ignore[method-assign]

    loop = LiveStreamLoop(
        pipeline,
        render=lambda *args: b"rendered-jpeg",
        reconnect_backoff_seconds=0.01,
        target_fps=1000.0,
    )

    loop.start()
    assert recovered.wait(timeout=1.0)
    loop.stop()

    assert loop.failure is None
    assert pipeline.open_count == 2  # 최초 open + 재연결 open
    assert pipeline.close_count == 2  # 재연결 close + 최종 close


def test_live_stream_loop_reopens_for_replay_on_end_of_video_by_default() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    pipeline = _FramePipeline(eov_times=1)
    resumed = Event()
    original_process = pipeline.process_next_frame

    def process_next_frame(*, frame_observer=None):
        result = original_process(frame_observer=frame_observer)
        if pipeline.calls == pipeline._eov_times + 1:
            resumed.set()
        return result

    pipeline.process_next_frame = process_next_frame  # type: ignore[method-assign]

    loop = LiveStreamLoop(pipeline, render=lambda *args: b"rendered-jpeg", target_fps=1000.0)

    loop.start()
    assert resumed.wait(timeout=1.0)
    loop.stop()

    assert loop.failure is None
    assert pipeline.open_count == 2  # 최초 open + 반복재생을 위한 reopen
    assert pipeline.close_count == 2  # reopen close + 최종 close


def test_live_stream_loop_halts_on_end_of_video_when_looping_disabled() -> None:
    from src.live.live_stream_loop import LiveStreamLoop

    pipeline = _FramePipeline(eov_times=1)
    loop = LiveStreamLoop(
        pipeline,
        render=lambda *args: b"rendered-jpeg",
        loop_on_end_of_video=False,
        target_fps=1000.0,
    )

    loop.start()
    # loop_on_end_of_video=False이면 _loop()가 스스로 return해 스레드가 끝나고,
    # _run()의 finally가 pipeline.close()를 호출한다 — 이 close 호출을 기다려야
    # "스레드가 이미 끝났는지"를 뒤이은 stop()과 경쟁 조건 없이 확인할 수 있다.
    assert pipeline.closed.wait(timeout=1.0)
    loop.stop()

    assert loop.failure is None
    assert loop.is_running is False
    assert pipeline.open_count == 1  # reopen 없음
    assert pipeline.calls == 1
    jpeg_bytes = loop.latest_jpeg()
    assert jpeg_bytes is not None
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3)

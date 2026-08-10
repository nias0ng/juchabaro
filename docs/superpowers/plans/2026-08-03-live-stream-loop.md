# 479 라이브 스트림 루프(live_stream_loop) 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `MonitoringPipeline`을 백그라운드 스레드에서 돌리며 478의 `render_overlay_jpeg`로 매 프레임을 오버레이 JPEG로 그려 스레드 세이프 단일 슬롯 버퍼에 게시하는 `src/live/live_stream_loop.py`를 새로 만든다. (`docs/superpowers/specs/2026-08-03-live-demo-streaming-design.md`의 컴포넌트 3.)

**Architecture:** `MonitoringWorker`를 재사용하지 않는다 — 카메라 재연결 백오프, 리허설 영상 반복재생, 프레임레이트 캡 같은 데모 전용 정책이 있어 `scripts/replay_pilot_video.py`처럼 `MonitoringPipeline.process_next_frame(frame_observer=...)`를 직접 호출하는 자체 루프(`LiveStreamLoop`)가 필요하다. 버퍼(`LatestFrameBuffer`)·프레임레이트 계산(`_throttle_sleep_seconds`)·안내 프레임 생성(`_placeholder_jpeg`)을 각각 독립된 순수/경량 유닛으로 분리해 스레드 타이밍 없이 테스트한다.

**Tech Stack:** Python, OpenCV(`cv2`)·numpy(이미 `hw/jetson/requirements.txt`에 존재), threading(표준 라이브러리), pytest.

## Global Constraints

- `render_overlay_jpeg`/`draw_overlay`/`encode_jpeg` 등 **렌더링·인코딩 실패는 이 모듈이 잡아 placeholder 프레임으로 대체**한다 — `MonitoringPipeline`으로 예외가 전파되면 `MonitoringWorker`류가 이를 치명 오류로 취급해 카메라·모델을 끈다(`hw/jetson/src/live/live_overlay_renderer.py`의 `encode_jpeg` docstring, `docs/superpowers/specs/2026-08-03-live-demo-streaming-design.md` 에러 처리 섹션).
- **재연결은 반드시 `pipeline.close()` 후 `pipeline.open()`** 순서로 한다 — `OpenCvWebcamFrameSource.open()`은 `self._capture is not None`이면 즉시 반환하는 no-op이라(`hw/jetson/src/camera/frame_source.py:281-282`), `close()`로 `_capture`를 `None`으로 되돌리지 않으면 재연결이 실제로 일어나지 않는다.
- **`EndOfVideo`는 `FrameSourceError`의 서브클래스**이므로 `except` 절 순서가 중요하다 — `except EndOfVideo` 절이 반드시 `except FrameSourceError` 절보다 먼저 와야 한다. `MonitoringPipeline.process_next_frame`도 같은 순서를 쓴다(`monitoring_pipeline.py:127-136`).
- **재연결 백오프는 고정 2.0초**(구성 가능한 생성자 인자, 기본값 2.0), **프레임레이트 캡은 기본 15fps**다. fps 캡은 소스의 실제 fps를 조회하지 않는다 — 매 반복 처리에 걸린 경과시간만 재서 목표 간격(1/target_fps초)보다 빠르면 그 차이만큼 `sleep`한다. 리허설처럼 원본이 이미 그보다 느리면 자연히 sleep이 0이 되어 영향이 없다.
- **`EndOfVideo` 시 기본 동작은 반복재생**(`loop_on_end_of_video=True` 기본값) — `pipeline.close()`+`pipeline.open()`으로 다시 열어 계속 스트리밍한다. `loop_on_end_of_video=False`면 "정지" 안내 placeholder를 게시하고 루프 스레드가 스스로 끝난다(별도 종료 요청 없이).
- 이 작업은 `docs/superpowers/specs/2026-08-03-live-demo-streaming-design.md`의 컴포넌트 3까지만 구현한다. FastAPI `/live/stream` 라우터(컴포넌트 4)는 480의 범위다.

---

### Task 1: `LiveStreamLoop`과 지원 유닛 구현

**Files:**
- Create: `hw/jetson/src/live/live_stream_loop.py`
- Test: `hw/jetson/tests/live/test_live_stream_loop.py`

**Interfaces:**
- Consumes: `MonitoringPipeline`(`open()`/`process_next_frame(*, frame_observer=None)`/`close()`, `src/application/monitoring_pipeline.py`), `FrameObserver` 타입 별칭(같은 파일), `EndOfVideo`/`FrameSourceError`(`src/camera/frame_source.py`), `CapturedFrame`(`src/camera/models.py`), `TrackingBatch`(`src/tracking/models.py`), `FrameObservationResult`(`src/application/frame_observation_workflow.py`), `ZoneRegistry`(`src/parking/zone_registry.py`), `render_overlay_jpeg`/`encode_jpeg`(`src/live/live_overlay_renderer.py`, 478).
- Produces: `LatestFrameBuffer`(`publish(jpeg_bytes: bytes) -> None`, `get_latest() -> bytes | None`), `LiveStreamLoop(pipeline: MonitoringPipeline, *, zones: ZoneRegistry | None = None, jpeg_quality: int = 80, loop_on_end_of_video: bool = True, reconnect_backoff_seconds: float = 2.0, target_fps: float = 15.0, render: Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], bytes] | None = None)` — `start()`/`stop()`/`is_running`(property)/`failure`(property)/`latest_jpeg() -> bytes | None`. 480은 `latest_jpeg()`을 폴링해 MJPEG 응답을 만든다.

- [ ] **Step 1: 실패하는 테스트 작성 — `LatestFrameBuffer`는 최신 프레임만 덮어쓴다**

`hw/jetson/tests/live/test_live_stream_loop.py`를 새로 만든다:

```python
"""LiveStreamLoop과 지원 유닛(버퍼·throttle·placeholder)의 스레드 생명주기 테스트."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.live.live_stream_loop import (
    LatestFrameBuffer,
    LiveStreamLoop,
    _placeholder_jpeg,
    _throttle_sleep_seconds,
)


def test_latest_frame_buffer_starts_empty_and_overwrites() -> None:
    buffer = LatestFrameBuffer()

    assert buffer.get_latest() is None

    buffer.publish(b"first")
    assert buffer.get_latest() == b"first"

    buffer.publish(b"second")
    assert buffer.get_latest() == b"second"
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.live.live_stream_loop'`

- [ ] **Step 3: `live_stream_loop.py` 최초 구현 — `LatestFrameBuffer`**

`hw/jetson/src/live/live_stream_loop.py`를 만든다:

```python
"""MonitoringPipeline을 백그라운드 스레드에서 돌리며 오버레이 JPEG를 게시한다.

`MonitoringWorker`(`src/application/monitoring_worker.py`)를 재사용하지 않는다 —
카메라 재연결 백오프, 리허설 영상 반복재생, 프레임레이트 캡 같은 데모 전용
정책이 있어 `scripts/replay_pilot_video.py`처럼
`MonitoringPipeline.process_next_frame()`을 직접 호출하는 자체 루프가 필요하다.
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
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: 실패하는 테스트 작성 — `_throttle_sleep_seconds`**

`test_live_stream_loop.py`에 추가:

```python
def test_throttle_sleep_seconds_returns_remaining_interval_when_faster_than_target() -> None:
    # target_fps=15 -> 목표 간격 1/15초 ~= 0.0667초. 0.02초 만에 끝났으면 나머지를 재운다.
    remaining = _throttle_sleep_seconds(0.02, target_fps=15.0)

    assert remaining == pytest.approx(1.0 / 15.0 - 0.02)


def test_throttle_sleep_seconds_returns_zero_when_slower_than_target() -> None:
    # 원본 소스가 이미 목표보다 느리면(예: 5fps 리허설 영상) sleep을 추가하지 않는다.
    remaining = _throttle_sleep_seconds(1.0, target_fps=15.0)

    assert remaining == 0.0
```

- [ ] **Step 6: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: 새 2개 FAIL — `ImportError: cannot import name '_throttle_sleep_seconds'`

- [ ] **Step 7: `_throttle_sleep_seconds` 구현**

`live_stream_loop.py`의 `LatestFrameBuffer` 클래스 뒤에 추가:

```python
def _throttle_sleep_seconds(elapsed_seconds: float, *, target_fps: float = _TARGET_FPS) -> float:
    """목표 fps 간격보다 빨리 처리됐으면 나머지 대기 시간을, 아니면 0을 반환한다.

    소스의 실제 fps를 조회하지 않는다 — 리허설 영상처럼 원본이 이미 이 값보다
    느리면 `elapsed_seconds`가 목표 간격을 넘어서 자연히 0을 반환한다.
    """

    target_interval = 1.0 / target_fps
    remaining = target_interval - elapsed_seconds
    return remaining if remaining > 0.0 else 0.0
```

- [ ] **Step 8: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: 실패하는 테스트 작성 — `_placeholder_jpeg`**

`test_live_stream_loop.py`에 추가:

```python
def test_placeholder_jpeg_returns_decodable_bytes() -> None:
    jpeg_bytes = _placeholder_jpeg("카메라 연결 끊김")

    assert isinstance(jpeg_bytes, bytes)
    assert len(jpeg_bytes) > 0
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3)
```

- [ ] **Step 10: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: 새 1개 FAIL — `ImportError: cannot import name '_placeholder_jpeg'`

- [ ] **Step 11: `_placeholder_jpeg` 구현**

`live_stream_loop.py`의 `_throttle_sleep_seconds` 함수 뒤에 추가:

```python
def _placeholder_jpeg(message: str) -> bytes:
    """카메라 재연결 대기·리허설 종료 등 판정 프레임이 없을 때 보여줄 안내 프레임."""

    canvas = np.zeros((_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3), dtype=np.uint8)
    cv2.putText(
        canvas, message, (24, _PLACEHOLDER_HEIGHT // 2),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
    )
    return encode_jpeg(canvas)
```

- [ ] **Step 12: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: PASS (4 tests)

- [ ] **Step 13: 실패하는 테스트 작성 — `LiveStreamLoop` 정상 경로(시작·렌더 게시·정지)**

`test_live_stream_loop.py`에 추가:

```python
from threading import Event


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
    with pytest.raises(ValueError, match="zones.*render|render.*zones"):
        LiveStreamLoop(_FramePipeline())


def test_live_stream_loop_publishes_rendered_frames_and_stops_cleanly() -> None:
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
```

- [ ] **Step 14: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: 새 2개 FAIL — `ImportError: cannot import name 'LiveStreamLoop'`

- [ ] **Step 15: `LiveStreamLoop` 골격 구현 — 생성자 검증, 시작·정지, 정상 프레임 처리**

`live_stream_loop.py`의 `_placeholder_jpeg` 함수 뒤에 추가:

```python
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
        loop_on_end_of_video: bool = True,
        reconnect_backoff_seconds: float = _RECONNECT_BACKOFF_SECONDS,
        target_fps: float = _TARGET_FPS,
        render: RenderFn | None = None,
    ) -> None:
        if render is None and zones is None:
            raise ValueError("zones 또는 render 중 하나는 반드시 지정해야 합니다")
        self._pipeline = pipeline
        self._loop_on_end_of_video = loop_on_end_of_video
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
            self._pipeline.process_next_frame(frame_observer=self._on_frame)
            elapsed = time.monotonic() - started_at
            wait_seconds = _throttle_sleep_seconds(elapsed, target_fps=self._target_fps)
            if wait_seconds > 0.0:
                self._stop_requested.wait(wait_seconds)

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
            jpeg_bytes = _placeholder_jpeg("렌더링 오류")
        self._buffer.publish(jpeg_bytes)
```

- [ ] **Step 16: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: PASS (6 tests)

- [ ] **Step 17: 실패하는 테스트 작성 — 렌더링 실패는 placeholder로 격리되고 루프는 계속된다**

`test_live_stream_loop.py`에 추가:

```python
def test_live_stream_loop_falls_back_to_placeholder_when_render_fails() -> None:
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
```

- [ ] **Step 18: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py::test_live_stream_loop_falls_back_to_placeholder_when_render_fails -v`
Expected: PASS 또는 FAIL — Step 15의 `_on_frame`이 이미 try/except를 구현했으므로 이 테스트는 **이미 통과할 것으로 예상**된다. 만약 FAIL하면 Step 15 구현을 다시 확인한다(회귀 방지용 테스트로 유지).

- [ ] **Step 19: 실패하는 테스트 작성 — `FrameSourceError`는 placeholder 게시 후 재연결한다**

`test_live_stream_loop.py`에 추가:

```python
def test_live_stream_loop_reconnects_after_frame_source_error() -> None:
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
```

- [ ] **Step 20: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py::test_live_stream_loop_reconnects_after_frame_source_error -v`
Expected: FAIL — `_loop`가 아직 `FrameSourceError`를 잡지 않아 예외가 `_run`까지 전파되고 `loop.failure`가 `FrameSourceError`가 됨(재연결이 일어나지 않음).

- [ ] **Step 21: `FrameSourceError` 재연결 구현**

`live_stream_loop.py`의 `_loop` 메서드를 교체:

```python
    def _loop(self) -> None:
        while not self._stop_requested.is_set():
            started_at = time.monotonic()
            try:
                self._pipeline.process_next_frame(frame_observer=self._on_frame)
            except EndOfVideo:
                if not self._reopen_for_replay():
                    return
                continue
            except FrameSourceError as error:
                LOGGER.warning("카메라 연결이 끊겼습니다: %s", error)
                self._buffer.publish(_placeholder_jpeg("카메라 연결 끊김 - 재연결 시도 중"))
                self._reconnect()
                continue
            elapsed = time.monotonic() - started_at
            wait_seconds = _throttle_sleep_seconds(elapsed, target_fps=self._target_fps)
            if wait_seconds > 0.0:
                self._stop_requested.wait(wait_seconds)

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
            except FrameSourceError as error:
                LOGGER.warning("재연결 실패, 다시 시도합니다: %s", error)

    def _reopen_for_replay(self) -> bool:
        """리허설 영상이 끝났을 때 반복재생하거나 정지 안내를 게시한다.

        Returns: 반복재생을 위해 다시 열었으면 True, 루프를 끝내야 하면 False.
        """

        if not self._loop_on_end_of_video:
            self._buffer.publish(_placeholder_jpeg("리허설 영상 종료"))
            return False
        self._pipeline.close()
        self._pipeline.open()
        return True
```

**주의:** `except EndOfVideo` 절이 `except FrameSourceError` 절보다 반드시 먼저 와야 한다(Global Constraints 참고) — `EndOfVideo`는 `FrameSourceError`의 서브클래스라 순서가 바뀌면 `EndOfVideo`가 재연결 경로로 잘못 빠진다.

- [ ] **Step 22: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -v`
Expected: PASS (8 tests)

- [ ] **Step 23: 실패하는 테스트 작성 — `EndOfVideo` 반복재생과 정지 모드**

`test_live_stream_loop.py`에 추가:

```python
def test_live_stream_loop_reopens_for_replay_on_end_of_video_by_default() -> None:
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
```

- [ ] **Step 24: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_stream_loop.py -k end_of_video -v`
Expected: `test_live_stream_loop_reopens_for_replay_on_end_of_video_by_default`는 이미 PASS(Step 21에서 함께 구현됨), `test_live_stream_loop_halts_on_end_of_video_when_looping_disabled`도 PASS 예상 — 두 테스트 모두 회귀 방지용으로 유지한다. 만약 FAIL하면 Step 21의 `_reopen_for_replay` 구현을 다시 확인한다.

- [ ] **Step 25: 전체 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/ -v`
Expected: 19개 테스트 전부 PASS (`test_live_overlay_renderer.py` 9개 + 이 계획으로 작성한 `test_live_stream_loop.py` 10개)

Run: `cd hw/jetson && uv run pytest -q`
Expected: 이전과 동일하게 `tests/evidence/test_spool.py`의 6개(Windows fsync 이슈, 이번 변경과 무관)만 실패하고 나머지는 전부 PASS.

- [ ] **Step 26: 커밋**

```bash
cd hw/jetson
git add src/live/live_stream_loop.py tests/live/test_live_stream_loop.py
git commit -m "$(cat <<'EOF'
feat(ai): 라이브 스트림 루프(live_stream_loop) 구현

MonitoringPipeline을 백그라운드 스레드에서 돌리며 478의
render_overlay_jpeg로 매 프레임을 오버레이 JPEG로 그려 스레드 세이프
단일 슬롯 버퍼(LatestFrameBuffer)에 게시한다. MonitoringWorker를
재사용하지 않고 replay_pilot_video.py처럼 process_next_frame을 직접
호출하는 자체 루프를 쓴다 — 카메라 재연결(FrameSourceError, 고정
2초 백오프, close()+open() 재시도), 리허설 영상 반복재생/정지
(EndOfVideo), 프레임레이트 캡(기본 15fps, 경과시간 기반 sleep)이
MonitoringWorker에는 없는 데모 전용 정책이기 때문이다. 렌더링·인코딩
실패는 이 루프가 잡아 placeholder 프레임으로 대체해 MonitoringPipeline
으로 전파하지 않는다.

479
EOF
)"
```

---

## Self-Review Notes

- **스펙 커버리지:** 설계 문서 컴포넌트 3("`src/live/live_stream_loop.py`(신규) — 캡처→추적→판정 루프를 백그라운드 스레드에서 실행, 렌더러 호출, 결과를 공유 버퍼에 게시")와 에러 처리 섹션의 세 항목(카메라 연결 끊김/재연결, 리플레이 EndOfVideo, frame_observer 콜백 예외)을 모두 Task 1에서 구현·테스트한다. 프레임레이트 캡(렌더링과 스트리밍 섹션)도 `_throttle_sleep_seconds`로 구현했다. 컴포넌트 4(`/live/stream` 라우터)는 이 계획의 범위 밖(480)이다.
- **자리표시자 스캔:** 모든 스텝에 실행 가능한 실제 코드가 있다. "TBD"/"나중에 구현" 없음.
- **타입 일관성:** `LiveStreamLoop.latest_jpeg() -> bytes | None`, `LatestFrameBuffer.publish(bytes) -> None`/`get_latest() -> bytes | None`, `RenderFn = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], bytes]` — Step 3/7/11/15/21에서 정의한 이름과 시그니처가 이후 스텝에서 그대로 쓰인다.

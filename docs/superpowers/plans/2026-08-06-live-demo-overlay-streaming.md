# 시연용 라이브 오버레이 스트리밍 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영 `MonitoringWorker`가 돌리는 실제 판정 파이프라인의 오버레이를 `/live/stream` MJPEG로 내보내고, 위반 사건을 그 화면에 표시한다.

**Architecture:** `MonitoringPipeline`에 이미 있는 `frame_observer` 훅(`monitoring_pipeline.py:181`, commit 성공 후 호출)을 `MonitoringWorker`가 통과시키도록 뚫고, 그 훅에 `OverlayPublisher`(렌더 → 단일 슬롯 버퍼 게시)를 꽂는다. FastAPI 라우터는 그 버퍼를 `multipart/x-mixed-replace`로 읽기만 한다. 카메라도 추론도 한 번만 돈다.

**Tech Stack:** Python 3.10, FastAPI, OpenCV, pydantic-settings, pytest

## Global Constraints

- 대상 디렉터리는 `hw/jetson`. 모든 명령은 레포 루트에서 `python -m pytest hw/jetson/tests`로 실행할 수 있다(`pyproject.toml`이 `pythonpath`를 잡아준다).
- **`frame_observer` 구현체는 자신의 모든 예외를 스스로 처리해야 한다.** 예외가 `MonitoringPipeline`으로 전파되면 `MonitoringWorker._run()`이 치명 오류로 잡아 카메라·모델을 전부 닫는다(`monitoring_worker.py:76-85`). 이 정책은 의도된 설계이며 바꾸지 않는다.
- **`frame_observer` 안에서 절대 sleep하지 않는다.** 이 콜백은 판정 루프와 같은 스레드에서 돈다. 프레임레이트 제한은 대기가 아니라 **프레임 드롭**으로 구현한다.
- `src/live/live_stream_loop.py`의 `LiveStreamLoop`는 이 기능에 사용하지 않는다. 자체 캡처 루프를 갖고 있어 운영 `MonitoringWorker`와 함께 돌리면 카메라를 두 번 열고 추론을 두 번 한다. `LatestFrameBuffer`·placeholder 프레임 같은 조각만 공유한다.
- 새 설정의 기본값은 **꺼짐**이다. 운영 배포에 MJPEG 인코딩 비용을 기본으로 얹지 않는다.
- 커밋 메시지 형식은 `<종류>(<모듈명>): <작업 내용> (<Jira 키>)`. 모듈명은 `hw`.
- 한 Jira Task = 한 브랜치 = 한 MR. 아래 Task 2와 Task 3은 **같은 브랜치·같은 MR**이고, Task 1과 Task 4는 각각 별도다.

## Jira / 브랜치 매핑

| Plan Task | 브랜치 | 내용 |
|---|---|---|
| Task 1 | `feature/hw/<키>-monitoring-worker-frame-observer` | `MonitoringWorker`에 `frame_observer` 통과 |
| Task 2 + Task 3 | `feature/hw/<키>-live-overlay-stream` | `OverlayPublisher` + `/live/stream` 라우터 + 배선 |
| Task 4 | `feature/hw/<키>-overlay-incident-rendering` | 오버레이 Incident 표시 |

Task 4는 Task 1~3과 **독립적으로 병행 가능**하다(순수 렌더러 변경). Task 3은 Task 1·2에 의존한다.

## File Structure

| 파일 | 책임 | 상태 |
|---|---|---|
| `hw/jetson/src/application/monitoring_worker.py` | 파이프라인 스레드 생명주기. `frame_observer`를 받아 `pipeline.run()`으로 전달만 한다 | 수정 |
| `hw/jetson/src/live/frame_publishing.py` | 스레드 세이프 단일 슬롯 JPEG 버퍼와 안내 프레임 생성 | **신규** |
| `hw/jetson/src/live/overlay_publisher.py` | `FrameObserver` 구현체. 렌더 → 예외 흡수 → 프레임 드롭 → 버퍼 게시 | **신규** |
| `hw/jetson/src/live/live_stream_loop.py` | 기존 자체 캡처 루프. 옮겨간 조각을 import만 하도록 수정 | 수정 |
| `hw/jetson/src/live/live_overlay_renderer.py` | 프레임 위에 구역·차량·**사건**을 그린다 | 수정 |
| `hw/jetson/src/api/live_stream_router.py` | `GET /live`(뷰어 페이지), `GET /live/stream`(MJPEG) | **신규** |
| `hw/jetson/src/config/settings.py` | 라이브 스트리밍 on/off·fps·품질 설정 | 수정 |
| `hw/jetson/src/main.py` | publisher 조립, worker 주입, 라우터 등록 | 수정 |
| `hw/jetson/.env.example` | 새 설정 문서화 | 수정 |

---

### Task 1: `MonitoringWorker`에 `frame_observer` 통과

**Files:**
- Modify: `hw/jetson/src/application/monitoring_worker.py:27-31,71-75`
- Test: `hw/jetson/tests/application/test_monitoring_worker.py`
- Test: `hw/jetson/tests/test_main.py:13-31` (fake 시그니처만 맞춤)

**Interfaces:**
- Consumes: `MonitoringPipeline.run(*, result_consumer=None, frame_observer=None, stop_requested=None) -> int` (`monitoring_pipeline.py:240`), `FrameObserver = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], None]` (`monitoring_pipeline.py:37`)
- Produces: `MonitoringWorker(pipeline, *, frame_observer: FrameObserver | None = None)` — Task 3의 `main.py` 배선이 이 시그니처를 쓴다.

- [ ] **Step 1: 기존 fake pipeline 두 개가 `frame_observer` 인자를 받도록 시그니처를 맞춘다**

`MonitoringWorker._run()`이 항상 `frame_observer=`를 넘기게 되므로, 이걸 먼저 해두지 않으면 Step 4에서 기존 테스트가 `TypeError`로 무더기로 깨진다. fake는 값을 무시하기만 하면 된다.

`hw/jetson/tests/application/test_monitoring_worker.py`의 `_BlockingPipeline.run`과 `_RunFailingPipeline.run`:

```python
class _BlockingPipeline:
    def __init__(self) -> None:
        self.opened = False
        self.entered_run = Event()
        self.closed = Event()

    def open(self) -> None:
        self.opened = True

    def run(self, *, stop_requested, frame_observer=None) -> int:
        del frame_observer
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 4

    def close(self) -> None:
        self.closed.set()
```

```python
class _RunFailingPipeline(_BlockingPipeline):
    def run(self, *, stop_requested, frame_observer=None) -> int:
        del stop_requested, frame_observer
        self.entered_run.set()
        raise RuntimeError("inference failed")
```

`hw/jetson/tests/test_main.py`의 `_BlockingPipeline.run`도 같은 방식으로:

```python
    def run(self, *, stop_requested, frame_observer=None) -> int:
        del frame_observer
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 0
```

- [ ] **Step 2: 실패하는 테스트를 작성한다**

`hw/jetson/tests/application/test_monitoring_worker.py` 맨 아래에 추가:

```python
class _ObserverCapturingPipeline(_BlockingPipeline):
    def __init__(self) -> None:
        super().__init__()
        self.received_observer: object = "not-called"

    def run(self, *, stop_requested, frame_observer=None) -> int:
        self.received_observer = frame_observer
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 0


def test_worker_forwards_frame_observer_to_pipeline_run() -> None:
    pipeline = _ObserverCapturingPipeline()

    def observer(frame, tracking_batch, result) -> None:
        del frame, tracking_batch, result

    worker = MonitoringWorker(pipeline, frame_observer=observer)

    worker.start()
    assert pipeline.entered_run.wait(timeout=1.0)
    worker.stop()

    assert pipeline.received_observer is observer


def test_worker_forwards_none_when_no_frame_observer_configured() -> None:
    pipeline = _ObserverCapturingPipeline()
    worker = MonitoringWorker(pipeline)

    worker.start()
    assert pipeline.entered_run.wait(timeout=1.0)
    worker.stop()

    assert pipeline.received_observer is None
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/application/test_monitoring_worker.py -v`
Expected: `test_worker_forwards_frame_observer_to_pipeline_run`이 `TypeError: MonitoringWorker.__init__() got an unexpected keyword argument 'frame_observer'`로 FAIL. `test_worker_forwards_none_when_no_frame_observer_configured`도 `received_observer == "not-called"`로 FAIL.

- [ ] **Step 4: 최소 구현을 작성한다**

`hw/jetson/src/application/monitoring_worker.py`의 import에 `FrameObserver`를 추가한다:

```python
from src.application.monitoring_pipeline import FrameObserver, MonitoringPipeline
```

`__init__`을 교체한다:

```python
    def __init__(
        self,
        pipeline: MonitoringPipeline,
        *,
        frame_observer: FrameObserver | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._frame_observer = frame_observer
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._failure: Exception | None = None
```

`_run()`의 `pipeline.run()` 호출을 교체한다:

```python
    def _run(self) -> None:
        try:
            self._pipeline.run(
                stop_requested=self._stop_requested.is_set,
                frame_observer=self._frame_observer,
            )
```

클래스 docstring 끝에 한 줄 덧붙인다:

```python
    """카메라·model pipeline을 하나의 background thread에서 실행한다.

    ``start()``는 model·camera open이 성공한 후에만 복귀하므로 기동
    실패를 API readiness로 숨기지 않는다. ``stop()``은 새 frame 시작을
    막고 진행 중인 frame의 transaction이 끝난 뒤 자원 정리를 기다린다.

    ``frame_observer``는 그대로 ``pipeline.run()``에 전달만 한다 — 이
    worker는 관측 내용을 해석하지 않는다. 콜백이 예외를 던지면
    ``_run()``이 이를 치명 오류로 처리해 카메라·모델을 닫으므로, 예외
    흡수 책임은 콜백 구현체에 있다.
    """
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/application/test_monitoring_worker.py hw/jetson/tests/test_main.py -v`
Expected: 전부 PASS

- [ ] **Step 6: 커밋한다**

```bash
git add hw/jetson/src/application/monitoring_worker.py hw/jetson/tests/application/test_monitoring_worker.py hw/jetson/tests/test_main.py
git commit -m "feat(hw): MonitoringWorker가 frame_observer를 파이프라인에 전달"
```

---

### Task 2: `OverlayPublisher` — 운영 루프에 붙는 오버레이 게시자

**Files:**
- Create: `hw/jetson/src/live/frame_publishing.py`
- Create: `hw/jetson/src/live/overlay_publisher.py`
- Modify: `hw/jetson/src/live/live_stream_loop.py:16-19,29-34,39-52,67-79,114,118-120`
- Modify: `hw/jetson/tests/live/test_live_stream_loop.py:13-16` (import 경로만)
- Test: `hw/jetson/tests/live/test_overlay_publisher.py`

**Interfaces:**
- Consumes: `render_overlay_jpeg(frame, tracking_batch, result, *, zones, jpeg_quality=80) -> bytes` (`live_overlay_renderer.py:96`), `encode_jpeg(canvas, *, jpeg_quality=80) -> bytes` (`:81`)
- Produces:
  - `LatestFrameBuffer` — `.publish(bytes) -> None`, `.get_latest() -> bytes | None`
  - `placeholder_jpeg(message: str) -> bytes`
  - `DEFAULT_TARGET_FPS: float = 15.0`
  - `OverlayPublisher(*, zones=None, jpeg_quality=80, target_fps=DEFAULT_TARGET_FPS, render=None, monotonic=time.monotonic)` — 호출 가능 객체(`__call__(frame, tracking_batch, result) -> None`)이자 `.latest_jpeg() -> bytes | None`. Task 3이 이 두 가지를 쓴다.

- [ ] **Step 1: 공유 조각을 새 모듈로 옮긴다**

`hw/jetson/src/live/frame_publishing.py`를 만든다:

```python
"""라이브 오버레이 발행에 공통으로 쓰는 단일 슬롯 버퍼와 안내 프레임.

`LiveStreamLoop`(자체 캡처 루프를 가진 개발용 도구)와 `OverlayPublisher`(운영
`MonitoringWorker`에 붙는 frame_observer)가 같은 구현을 쓰도록 여기로 모았다.
"""

from __future__ import annotations

from threading import Lock

import cv2
import numpy as np

from src.live.live_overlay_renderer import encode_jpeg

DEFAULT_TARGET_FPS = 15.0
PLACEHOLDER_HEIGHT = 480
PLACEHOLDER_WIDTH = 640


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
```

- [ ] **Step 2: `live_stream_loop.py`가 새 모듈을 쓰도록 고친다**

`hw/jetson/src/live/live_stream_loop.py`에서:

1. import 블록에서 `from threading import Event, Lock, Thread` → `from threading import Event, Thread`로 바꾸고, `import cv2` / `import numpy as np`를 지운다(더 이상 쓰지 않는다).
2. `from src.live.live_overlay_renderer import encode_jpeg, render_overlay_jpeg` → `from src.live.live_overlay_renderer import render_overlay_jpeg`
3. 그 아래에 추가:

```python
from src.live.frame_publishing import (
    DEFAULT_TARGET_FPS,
    LatestFrameBuffer,
    placeholder_jpeg,
)
```

4. 모듈 상수를 교체한다:

```python
_TARGET_FPS = DEFAULT_TARGET_FPS
_RECONNECT_BACKOFF_SECONDS = 2.0
```

(`_PLACEHOLDER_HEIGHT`, `_PLACEHOLDER_WIDTH` 두 줄은 삭제한다.)

5. `class LatestFrameBuffer:` 정의 전체(39~52행)와 `def _placeholder_jpeg(...)` 정의 전체(67~79행)를 삭제한다.
6. `__init__` 안의 세 개 placeholder 생성 호출을 새 이름으로 바꾼다:

```python
        self._reconnecting_placeholder_jpeg = placeholder_jpeg("CAMERA DISCONNECTED - RECONNECTING")
        self._video_ended_placeholder_jpeg = placeholder_jpeg("VIDEO ENDED")
        self._render_error_placeholder_jpeg = placeholder_jpeg("RENDER ERROR")
```

`_throttle_sleep_seconds`는 **옮기지 않는다** — 자체 루프의 대기 계산이라 `OverlayPublisher`는 쓰지 않는다.

- [ ] **Step 3: 기존 테스트의 import를 고친다**

`hw/jetson/tests/live/test_live_stream_loop.py`의 import 블록(12~19행)을 통째로 교체한다. 옮겨간 이름 넷(`LatestFrameBuffer`, `placeholder_jpeg`, `PLACEHOLDER_HEIGHT`, `PLACEHOLDER_WIDTH`)만 새 모듈에서 가져오고, 루프 전용인 `_throttle_sleep_seconds`와 `LiveStreamLoop`는 그대로 둔다:

```python
from src.live.frame_publishing import (
    LatestFrameBuffer,
    PLACEHOLDER_HEIGHT,
    PLACEHOLDER_WIDTH,
    placeholder_jpeg,
)
from src.live.live_stream_loop import (
    LiveStreamLoop,
    _throttle_sleep_seconds,
)
```

그리고 이름이 바뀐 호출부를 고친다:

- 49행의 `_placeholder_jpeg("CAMERA DISCONNECTED")` → `placeholder_jpeg("CAMERA DISCONNECTED")`
- 55·144·198행의 `(_PLACEHOLDER_HEIGHT, _PLACEHOLDER_WIDTH, 3)` → `(PLACEHOLDER_HEIGHT, PLACEHOLDER_WIDTH, 3)`

- [ ] **Step 4: 리팩터링이 회귀를 만들지 않았는지 확인한다**

Run: `python -m pytest hw/jetson/tests/live -v`
Expected: 기존 테스트 전부 PASS (11개 이상)

- [ ] **Step 5: `OverlayPublisher`의 실패하는 테스트를 작성한다**

`hw/jetson/tests/live/test_overlay_publisher.py`를 만든다:

```python
"""OverlayPublisher의 게시·예외 흡수·프레임 드롭 계약 테스트."""

from __future__ import annotations

import pytest

from src.live.overlay_publisher import OverlayPublisher


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _publisher(render, clock, *, target_fps: float = 15.0) -> OverlayPublisher:
    return OverlayPublisher(render=render, target_fps=target_fps, monotonic=clock)


def test_latest_jpeg_is_none_before_any_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"jpeg", _FakeClock())

    assert publisher.latest_jpeg() is None


def test_publishes_rendered_bytes_on_first_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"first", _FakeClock())

    publisher(object(), object(), object())

    assert publisher.latest_jpeg() == b"first"


def test_drops_frames_arriving_faster_than_target_fps() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.05  # 목표 간격 0.1초의 절반 — 드롭돼야 한다
    publisher(object(), object(), object())

    assert rendered == [b"frame-0"]
    assert publisher.latest_jpeg() == b"frame-0"


def test_publishes_again_once_target_interval_has_passed() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.2
    publisher(object(), object(), object())

    assert rendered == [b"frame-0", b"frame-1"]
    assert publisher.latest_jpeg() == b"frame-1"


def test_swallows_render_failure_and_publishes_placeholder() -> None:
    def render(frame, tracking_batch, result) -> bytes:
        raise ValueError("render exploded")

    publisher = _publisher(render, _FakeClock())

    publisher(object(), object(), object())  # 예외가 밖으로 나오면 안 된다

    latest = publisher.latest_jpeg()
    assert latest is not None
    assert latest.startswith(b"\xff\xd8")  # JPEG SOI — placeholder가 들어갔다


def test_requires_zones_or_render() -> None:
    with pytest.raises(ValueError, match="zones 또는 render"):
        OverlayPublisher()


def test_rejects_non_positive_target_fps() -> None:
    with pytest.raises(ValueError, match="target_fps"):
        OverlayPublisher(render=lambda f, b, r: b"x", target_fps=0.0)
```

- [ ] **Step 6: 테스트가 실패하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/live/test_overlay_publisher.py -v`
Expected: 수집 단계에서 `ModuleNotFoundError: No module named 'src.live.overlay_publisher'`로 FAIL

- [ ] **Step 7: `OverlayPublisher`를 구현한다**

`hw/jetson/src/live/overlay_publisher.py`를 만든다:

```python
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
    placeholder_jpeg,
)
from src.live.live_overlay_renderer import render_overlay_jpeg
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import TrackingBatch

LOGGER = logging.getLogger(__name__)

RenderFn = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], bytes]
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
        self._render: RenderFn = render or (
            lambda frame, tracking_batch, result: render_overlay_jpeg(
                frame, tracking_batch, result, zones=zones, jpeg_quality=jpeg_quality
            )
        )
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
```

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/live -v`
Expected: 전부 PASS

- [ ] **Step 9: 커밋한다**

```bash
git add hw/jetson/src/live/frame_publishing.py hw/jetson/src/live/overlay_publisher.py hw/jetson/src/live/live_stream_loop.py hw/jetson/tests/live/
git commit -m "feat(hw): 운영 파이프라인용 오버레이 게시자 추가"
```

---

### Task 3: `/live/stream` MJPEG 라우터와 런타임 배선

**Files:**
- Create: `hw/jetson/src/api/live_stream_router.py`
- Modify: `hw/jetson/src/config/settings.py:69,191`
- Modify: `hw/jetson/.env.example`
- Modify: `hw/jetson/src/main.py:370-392,473-475`
- Test: `hw/jetson/tests/api/test_live_stream_router.py`

**Interfaces:**
- Consumes: `OverlayPublisher.latest_jpeg() -> bytes | None` (Task 2), `MonitoringWorker(pipeline, *, frame_observer=...)` (Task 1), `JetsonApiError(*, status_code, error_type, message, retryable=False, headers=None)` (`error_handlers.py:41`)
- Produces: `router` (FastAPI `APIRouter`) — `main.py`가 `include_router`로 등록한다. `app.state.overlay_publisher`가 라우터와 배선의 접점이다.

- [ ] **Step 1: 실패하는 라우터 테스트를 작성한다**

`hw/jetson/tests/api/test_live_stream_router.py`를 만든다:

```python
"""GET /live/stream의 MJPEG 계약과 비활성 경계 테스트."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.error_handlers import register_error_handlers
from src.api.live_stream_router import router


class _StubPublisher:
    def __init__(self, jpeg_bytes: bytes | None) -> None:
        self._jpeg_bytes = jpeg_bytes

    def latest_jpeg(self) -> bytes | None:
        return self._jpeg_bytes


def _client(publisher) -> TestClient:
    application = FastAPI()
    register_error_handlers(application)
    application.include_router(router)
    application.state.overlay_publisher = publisher
    return TestClient(application)


def _read_until(response, needle: bytes, *, max_chunks: int = 200) -> bytes:
    collected = b""
    for index, chunk in enumerate(response.iter_bytes()):
        collected += chunk
        if needle in collected:
            return collected
        if index >= max_chunks:
            break
    raise AssertionError(f"{needle!r}를 스트림에서 찾지 못했습니다")


def test_stream_serves_multipart_with_the_latest_jpeg() -> None:
    client = _client(_StubPublisher(b"\xff\xd8fake-jpeg-payload"))

    with client.stream("GET", "/live/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
        body = _read_until(response, b"fake-jpeg-payload")

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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/api/test_live_stream_router.py -v`
Expected: `ModuleNotFoundError: No module named 'src.api.live_stream_router'`로 FAIL

- [ ] **Step 3: 라우터를 구현한다**

`hw/jetson/src/api/live_stream_router.py`를 만든다:

```python
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
```

- [ ] **Step 4: 라우터 테스트가 통과하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/api/test_live_stream_router.py -v`
Expected: 3개 PASS

- [ ] **Step 5: 설정을 추가한다**

`hw/jetson/src/config/settings.py`의 `camera_height` 선언(69행) 바로 다음에 추가한다:

```python
    # 데모용 라이브 오버레이 MJPEG 스트리밍. 운영 배포는 기본값(꺼짐)을
    # 유지한다 — 켜면 매 프레임 JPEG 인코딩 비용이 판정 루프와 같은
    # thread에서 발생한다.
    live_stream_enabled: bool = False
    live_stream_target_fps: float = Field(default=15.0, gt=0.0)
    live_stream_jpeg_quality: int = Field(default=80, ge=1, le=100)
```

`hw/jetson/.env.example`의 `CAMERA_HEIGHT=0` 줄 다음에 추가한다:

```
# 데모용 라이브 오버레이 스트리밍. 운영 배포는 false를 유지한다.
# true면 GET /live 로 뷰어 페이지를, GET /live/stream 으로 MJPEG를 연다.
LIVE_STREAM_ENABLED=false
LIVE_STREAM_TARGET_FPS=15.0
LIVE_STREAM_JPEG_QUALITY=80
```

- [ ] **Step 6: 설정 기본값 테스트를 추가하고 확인한다**

`hw/jetson/tests/test_settings.py` 맨 아래에 추가한다. 이 파일의 기존 테스트와 같이 `Settings(_env_file=None)`을 쓴다 — 기본값 없는 필수 필드는 `tests/conftest.py`의 `REQUIRED_ENV`가 채워준다.

```python
def test_live_stream_is_disabled_by_default() -> None:
    """운영 배포가 MJPEG 인코딩 비용을 기본으로 떠안지 않는다."""

    settings = Settings(_env_file=None)

    assert settings.live_stream_enabled is False
    assert settings.live_stream_target_fps == 15.0
    assert settings.live_stream_jpeg_quality == 80


def test_live_stream_settings_parse_environment_variable_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_STREAM_ENABLED", "true")
    monkeypatch.setenv("LIVE_STREAM_TARGET_FPS", "10.0")
    monkeypatch.setenv("LIVE_STREAM_JPEG_QUALITY", "60")

    settings = Settings(_env_file=None)

    assert settings.live_stream_enabled is True
    assert settings.live_stream_target_fps == 10.0
    assert settings.live_stream_jpeg_quality == 60


def test_live_stream_rejects_non_positive_target_fps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_STREAM_TARGET_FPS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

Run: `python -m pytest hw/jetson/tests/test_settings.py -v`
Expected: PASS

- [ ] **Step 7: `main.py`에 배선한다**

import 블록에 추가한다:

```python
from src.api.live_stream_router import router as live_stream_router
from src.live.overlay_publisher import OverlayPublisher
```

`lifespan` 안에서, `monitoring_worker: MonitoringWorker | None = None`(370행) **바로 앞**에 삽입한다:

```python
        overlay_publisher: OverlayPublisher | None = None
        if resolved_settings.live_stream_enabled:
            overlay_publisher = OverlayPublisher(
                zones=zones,
                jpeg_quality=resolved_settings.live_stream_jpeg_quality,
                target_fps=resolved_settings.live_stream_target_fps,
            )
        application.state.overlay_publisher = overlay_publisher
```

`monitoring_worker = MonitoringWorker(pipeline)`(391행)를 교체한다:

```python
            monitoring_worker = MonitoringWorker(
                pipeline, frame_observer=overlay_publisher
            )
```

라우터 등록부(473~475행) 끝에 추가한다:

```python
    application.include_router(live_stream_router)
```

- [ ] **Step 8: 전체 테스트를 돌린다**

Run: `python -m pytest hw/jetson/tests -v`
Expected: 전부 PASS

- [ ] **Step 9: 커밋한다**

```bash
git add hw/jetson/src/api/live_stream_router.py hw/jetson/tests/api/test_live_stream_router.py hw/jetson/src/config/settings.py hw/jetson/tests/test_settings.py hw/jetson/.env.example hw/jetson/src/main.py
git commit -m "feat(hw): 라이브 오버레이 MJPEG 스트리밍 엔드포인트 추가"
```

---

### Task 4: 오버레이에 Incident 표시

**Files:**
- Modify: `hw/jetson/src/live/live_overlay_renderer.py:21,61-78,106-118`
- Test: `hw/jetson/tests/live/test_live_overlay_renderer.py:106-118`

**Interfaces:**
- Consumes: `ParkingPipelineResult.incident_updates: tuple[Incident, ...]` (`parking/models.py:832`), `Incident.physical_vehicle_id`, `Incident.state`, `Incident.key.rule_code` (`:706-724`), `IncidentState` (`:107`)
- Produces: 없음(렌더러 내부 변경). `draw_overlay`/`render_overlay_jpeg`의 시그니처는 바뀌지 않는다.

**왜 `incident_transitions`가 아니라 `incident_updates`인가.** `incident_transitions`는 OPEN·RESOLVE가 일어난 그 프레임에만 값이 있다. 그걸로 그리면 배지가 한 프레임만 번쩍이고 사라진다. `incident_updates`는 `IncidentReducer.reduce()`가 반환한 aggregate 스냅샷이고, reducer는 기존 Incident가 있으면 신호가 `MATCHED`가 아니어도 reduction을 돌려주므로(`incident_reducer.py:288-290`은 *기존 Incident가 없고* 신호도 `MATCHED`가 아닐 때만 `None`), 사건이 살아 있는 동안 매 프레임 현재 상태가 실린다. 덕분에 렌더러는 프레임 간 상태를 들고 있지 않아도 되고 순수 함수로 남는다.

- [ ] **Step 1: 테스트 헬퍼가 incident를 실을 수 있게 고친다**

`hw/jetson/tests/live/test_live_overlay_renderer.py`의 import 블록 `from src.parking.models import (...)`에 추가한다:

```python
    Incident,
    IncidentId,
    IncidentKey,
    IncidentState,
```

`_result()` 헬퍼(106~118행)를 교체한다:

```python
def _result(
    *,
    zone_visits: tuple[ZoneVisit, ...] = (),
    episodes: tuple[ParkingEpisode, ...] = (),
    incidents: tuple[Incident, ...] = (),
) -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=zone_visits,
            parking_episode_updates=episodes,
            incident_transitions=(),
            incident_updates=incidents,
        ),
        retired_physical_vehicle_ids=(),
    )
```

파일 맨 아래에 incident 팩토리를 추가한다. `Incident.__post_init__`은 OPEN·CLEAR_PENDING·RESOLVED에 `confirmed_at`을 요구하고, terminal(RESOLVED·CANCELED)에 `terminated_at`과 `termination_reason`을 함께 요구한다:

```python
def _incident(
    rule_code: str,
    *,
    state: IncidentState = IncidentState.OPEN,
    incident_suffix: int = 1,
) -> Incident:
    was_opened = state in {
        IncidentState.OPEN,
        IncidentState.CLEAR_PENDING,
        IncidentState.RESOLVED,
    }
    is_terminal = state in {IncidentState.RESOLVED, IncidentState.CANCELED}
    return Incident(
        incident_id=IncidentId(
            UUID(f"40000000-0000-4000-8000-00000000000{incident_suffix}")
        ),
        key=IncidentKey.for_zone_visit(
            ZoneVisitId(UUID("20000000-0000-4000-8000-000000000001")), rule_code
        ),
        physical_vehicle_id=VEHICLE_ID,
        state=state,
        observation=OBSERVED,
        confirm_trusted_seconds=0.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=0.0,
        clear_duration_seconds=0.0,
        record_version=1,
        publication_revision=0,
        first_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        trusted_sample_max_gap_seconds=1.0,
        zone_id=ZoneId(1),
        confirmed_at=NOW if was_opened else None,
        resolved_at=NOW if state is IncidentState.RESOLVED else None,
        terminated_at=NOW if is_terminal else None,
        termination_reason="test" if is_terminal else None,
    )
```

- [ ] **Step 2: 실패하는 테스트를 작성한다**

같은 파일 맨 아래에 추가한다. 배너가 화면 위쪽 40px를 덮으므로 이 테스트들은 `_frame(size=400)`을 써서 bbox(0.2~0.6 → y=80~240)가 배너와 겹치지 않게 한다:

```python
INCIDENT_COLOR = (40, 40, 255)


def _region_has_color(
    canvas: np.ndarray,
    color: tuple[int, int, int],
    *,
    y_start: int,
    y_end: int,
) -> bool:
    for y in range(y_start, y_end):
        if _row_has_color(canvas, y, color):
            return True
    return False


def test_draw_overlay_paints_incident_banner_when_incident_is_open() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(incidents=(_incident("DISABLED_ZONE_UNAUTHORIZED"),))

    canvas = draw_overlay(
        _frame(size=400), _tracking_batch((vehicle,)), result, zones=_zone_registry()
    )

    assert _region_has_color(canvas, INCIDENT_COLOR, y_start=0, y_end=40)


def test_draw_overlay_paints_incident_badge_under_the_vehicle_bbox() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(incidents=(_incident("AISLE_BLOCK"),))

    canvas = draw_overlay(
        _frame(size=400), _tracking_batch((vehicle,)), result, zones=_zone_registry()
    )

    # bbox 아래(y=240 이후)에 배지가 그려진다.
    assert _region_has_color(canvas, INCIDENT_COLOR, y_start=241, y_end=290)


def test_draw_overlay_does_not_paint_resolved_incident() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(
        incidents=(_incident("AISLE_BLOCK", state=IncidentState.RESOLVED),)
    )

    canvas = draw_overlay(
        _frame(size=400), _tracking_batch((vehicle,)), result, zones=_zone_registry()
    )

    assert not _region_has_color(canvas, INCIDENT_COLOR, y_start=0, y_end=400)


def test_draw_overlay_does_not_paint_candidate_incident() -> None:
    """CANDIDATE는 아직 확정 전이라 화면에 띄우지 않는다."""

    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(
        incidents=(_incident("AISLE_BLOCK", state=IncidentState.CANDIDATE),)
    )

    canvas = draw_overlay(
        _frame(size=400), _tracking_batch((vehicle,)), result, zones=_zone_registry()
    )

    assert not _region_has_color(canvas, INCIDENT_COLOR, y_start=0, y_end=400)


def test_draw_overlay_paints_nothing_extra_when_there_are_no_incidents() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))

    canvas = draw_overlay(
        _frame(size=400), _tracking_batch((vehicle,)), _result(), zones=_zone_registry()
    )

    assert not _region_has_color(canvas, INCIDENT_COLOR, y_start=0, y_end=400)
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/live/test_live_overlay_renderer.py -v`
Expected: 배너·배지 테스트 2개가 FAIL(사건 색이 화면에 없음). RESOLVED·CANDIDATE·no-incident 3개는 이미 PASS(아무것도 안 그리므로) — 회귀 방지용이다.

- [ ] **Step 4: 렌더러를 구현한다**

`hw/jetson/src/live/live_overlay_renderer.py`의 `from src.parking.models import ...`에 `Incident`와 `IncidentState`를 추가한다:

```python
from src.parking.models import (
    Incident,
    IncidentState,
    ParkingEpisode,
    ParkingState,
    ZoneType,
    ZoneVisit,
    ZoneVisitState,
)
```

모듈 상수에 추가한다(`_DEFAULT_JPEG_QUALITY` 위):

```python
# 사건 표시색은 bbox 상태 팔레트와 다른 축이다 — bbox 색은 주차·구역 상태를
# 계속 나타내고, 사건은 그 위에 겹쳐 그리는 별도 배지·배너로만 쓴다.
_INCIDENT_COLOR = (40, 40, 255)
_INCIDENT_BANNER_HEIGHT = 40
_ACTIVE_INCIDENT_STATES = frozenset({IncidentState.OPEN, IncidentState.CLEAR_PENDING})
```

`draw_overlay`에 한 줄을 추가한다:

```python
    canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
    _draw_zones(canvas, zones)
    _draw_vehicles(canvas, tracking_batch, result)
    _draw_incidents(canvas, tracking_batch, result)
    return canvas
```

`_draw_vehicles` 정의 바로 다음에 추가한다:

```python
def _draw_incidents(
    canvas: np.ndarray,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
) -> None:
    """확정된 사건을 차량별 배지와 상단 배너로 그린다.

    `incident_transitions`가 아니라 `incident_updates`를 읽는다 — 전자는 OPEN·
    RESOLVE가 일어난 프레임에만 값이 있어 배지가 한 프레임만 번쩍인다.
    """

    height, width = canvas.shape[:2]
    incidents_by_vehicle = _index_incidents(result.parking_result.incident_updates)
    if not incidents_by_vehicle:
        return

    for vehicle in tracking_batch.vehicles:
        incidents = incidents_by_vehicle.get(vehicle.physical_vehicle_id)
        if not incidents:
            continue
        x1 = int(vehicle.bbox.x1 * width)
        y2 = int(vehicle.bbox.y2 * height)
        for offset, incident in enumerate(incidents):
            baseline = min(height - 4, y2 + 18 + offset * 18)
            cv2.putText(
                canvas, incident.key.rule_code, (x1, baseline),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, _INCIDENT_COLOR, 2,
            )

    _draw_incident_banner(canvas, incidents_by_vehicle)


def _draw_incident_banner(
    canvas: np.ndarray,
    incidents_by_vehicle: Mapping[PhysicalVehicleId, tuple[Incident, ...]],
) -> None:
    """발표장 뒷자리에서도 읽히도록 활성 규칙코드를 상단에 크게 띄운다."""

    rule_codes = sorted(
        {
            incident.key.rule_code
            for incidents in incidents_by_vehicle.values()
            for incident in incidents
        }
    )
    width = canvas.shape[1]
    cv2.rectangle(
        canvas, (0, 0), (width, _INCIDENT_BANNER_HEIGHT), (0, 0, 0), thickness=-1
    )
    cv2.putText(
        canvas, " / ".join(rule_codes), (8, _INCIDENT_BANNER_HEIGHT - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, _INCIDENT_COLOR, 2,
    )


def _index_incidents(
    incidents: tuple[Incident, ...]
) -> Mapping[PhysicalVehicleId, tuple[Incident, ...]]:
    """확정된(OPEN·CLEAR_PENDING) 사건만 차량별로 모은다.

    CANDIDATE는 아직 확정 전이고 RESOLVED·CANCELED는 끝났으므로 그리지 않는다.
    """

    grouped: dict[PhysicalVehicleId, list[Incident]] = {}
    for incident in incidents:
        if incident.state not in _ACTIVE_INCIDENT_STATES:
            continue
        grouped.setdefault(incident.physical_vehicle_id, []).append(incident)
    return {
        vehicle_id: tuple(sorted(group, key=lambda item: item.key.rule_code))
        for vehicle_id, group in grouped.items()
    }
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest hw/jetson/tests/live/test_live_overlay_renderer.py -v`
Expected: 신규 5개를 포함해 전부 PASS. 기존 테스트는 사건이 없어 배너가 그려지지 않으므로 영향받지 않는다.

- [ ] **Step 6: 전체 테스트를 돌린다**

Run: `python -m pytest hw/jetson/tests -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋한다**

```bash
git add hw/jetson/src/live/live_overlay_renderer.py hw/jetson/tests/live/test_live_overlay_renderer.py
git commit -m "feat(hw): 라이브 오버레이에 확정 사건 배지와 배너 표시"
```

---

## 통합 검증 (Task 1~4 병합 후, D-3 리허설 전)

유닛테스트로는 확인할 수 없고 실제 파이프라인을 돌려야 알 수 있는 것들이다.

- [ ] **젯슨에서 실제 앱을 띄운다**

```bash
cd hw/jetson
# .env에 LIVE_STREAM_ENABLED=true 설정
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

브라우저로 `http://<젯슨IP>:8000/live`를 열어 오버레이가 나오는지 확인한다.

- [ ] **사건 배지가 여러 프레임 동안 유지되는지 확인한다**

차를 장애인 구역(zone 4)에 넣고, `DISABLED_ZONE_UNAUTHORIZED` 배지와 배너가 **한 번 번쩍이고 사라지는 게 아니라 계속 떠 있는지** 눈으로 확인한다.

계속 떠 있지 않으면 `incident_updates`가 매 프레임 활성 사건을 싣지 않는다는 뜻이다. 그때는 `OverlayPublisher`가 활성 사건 맵을 프레임 간에 들고 있다가 렌더러에 넘기도록 바꿔야 한다(렌더러는 순수 함수로 유지하고, 상태는 publisher가 소유한다).

- [ ] **판정 성능이 떨어지지 않는지 확인한다**

`LIVE_STREAM_ENABLED=false`와 `true`로 각각 돌려 프레임 처리율을 비교한다. 눈에 띄게 느려지면 `LIVE_STREAM_TARGET_FPS`를 10 이하로, `LIVE_STREAM_JPEG_QUALITY`를 60까지 낮춘다.

- [ ] **브라우저 탭을 닫았다 열어도 파이프라인이 계속 도는지 확인한다**

탭을 닫고 30초 뒤 다시 열어 스트림이 재개되는지, 그 사이 젯슨 로그에 사건 전이가 계속 기록됐는지 확인한다.

- [ ] **OBS 브라우저 소스로 `http://<젯슨IP>:8000/live`를 잡는다**

씬 B·C에서 쓸 크기·위치를 잡아둔다.

## 이 계획이 다루지 않는 것

- **젯슨 LED·스피커 actuator 구현.** 다른 팀원이 개발 중인 기능으로 전제한다(`docs/superpowers/specs/2026-08-06-live-demo-scenario-design.md` §이 설계가 다루지 않는 것).
- **`.env.demo` 임계값 튜닝.** 코드 변경이 아니라 D-5 리허설의 설정 작업이다.
- **다수 동시 시청자·원격 시청.** 같은 네트워크의 소수 시청자만 대상으로 한다.
- **`LiveStreamLoop`의 폐기.** 개발용 `watch_live_stream.py`가 계속 쓰므로 남겨둔다.

# 477 라이브 프레임 관측 콜백 추가 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `MonitoringPipeline`이 프레임을 커밋한 직후, 그 프레임의 원본 이미지·bbox(`TrackingBatch`)·판정 결과(`FrameObservationResult`)를 선택적 콜백으로 넘겨줄 수 있게 한다 — 실시간 데모 오버레이가 판정용 추론을 다시 돌리지 않고 같은 1회 추론 결과를 그대로 그릴 수 있도록.

**Architecture:** `process_next_frame()`에 키워드 전용 `frame_observer` 파라미터를 추가하고, `_commit_batch()`가 만든 `result`와 함께 `(frame, tracking_batch, result)`로 호출한다. `run()`에도 같은 파라미터를 추가해 매 프레임 `process_next_frame()`으로 그대로 전달한다. 콜백을 넘기지 않으면 기존 replay 경로는 코드 경로가 전혀 바뀌지 않는다.

**Tech Stack:** Python, pytest (`hw/jetson`, `pytest.ini_options` testpaths=["tests"]).

## Global Constraints

- 콜백을 넘기지 않을 때 기존 동작(모든 기존 replay 결정론 테스트 포함)은 한 글자도 바뀌지 않아야 한다 — `frame_observer: FrameObserver | None = None` 키워드 전용 기본값.
- 콜백은 정상 커밋이 끝난 뒤에만 호출한다. `_commit_interruption()` 경로(카메라 장애, 추적 장애)는 예외를 그대로 전파하므로 콜백을 호출하지 않는다 — 이 경로엔 신뢰할 수 있는 `frame`/`tracking_batch`가 없다.
- 콜백 예외는 숨기지 않는다(`result_consumer`와 같은 정책, docstring에 이미 명시된 전제).
- `frame`은 `src/camera/models.py`의 `CapturedFrame`(RGB uint8 `image`, `calibration_id` 등), `tracking_batch`는 `src/tracking/models.py`의 `TrackingBatch`(`vehicles: tuple[PhysicalVehicleSnapshot, ...]`, 각 `bbox`는 0~1 정규화 `BoundingBox`) 타입이다.

---

### Task 1: `process_next_frame()`과 `run()`에 `frame_observer` 훅 추가

**Files:**
- Modify: `hw/jetson/src/application/monitoring_pipeline.py`
- Test: `hw/jetson/tests/application/test_monitoring_pipeline.py`

**Interfaces:**
- Consumes: 기존 `MonitoringPipeline.__init__`, `_commit_batch()`, `FrameObservationResult`(`hw/jetson/src/application/frame_observation_workflow.py`), `TrackingBatch`(`hw/jetson/src/tracking/models.py`), `CapturedFrame`(`hw/jetson/src/camera/models.py`).
- Produces: `FrameObserver = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], None]` (모듈 레벨 type alias), `MonitoringPipeline.process_next_frame(self, *, frame_observer: FrameObserver | None = None) -> FrameObservationResult`, `MonitoringPipeline.run(self, *, result_consumer=None, frame_observer: FrameObserver | None = None, stop_requested=None) -> int`. 이후 라이브 스트리밍 작업(478/479)이 이 시그니처로 오버레이 렌더러를 배선한다.

- [ ] **Step 1: 실패하는 테스트부터 작성 — `process_next_frame`이 커밋 후 관측자를 호출한다**

`hw/jetson/tests/application/test_monitoring_pipeline.py` 기존 fixture(`_FrameSource`, `_TrackingPipeline`, `_FrameWorkflow`, `_pipeline`)를 그대로 쓴다. 파일 하단(마지막 테스트 뒤)에 추가:

```python
def test_process_next_frame_calls_frame_observer_after_commit() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1")
    frame_source = _FrameSource([frame])
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)
    observed: list[tuple] = []

    result = pipeline.process_next_frame(
        frame_observer=lambda f, batch, r: observed.append((f, batch, r))
    )

    assert len(observed) == 1
    observed_frame, observed_batch, observed_result = observed[0]
    assert observed_frame is frame
    assert observed_batch in workflow.batches
    assert observed_result is result
    assert observed_result is workflow.results[0]
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py::test_process_next_frame_calls_frame_observer_after_commit -v`
Expected: FAIL — `TypeError: process_next_frame() got an unexpected keyword argument 'frame_observer'`

- [ ] **Step 3: `process_next_frame()`에 `frame_observer` 파라미터 구현**

`hw/jetson/src/application/monitoring_pipeline.py` 상단 import에 `CapturedFrame` 추가:

```python
from src.camera.frame_source import EndOfVideo, FrameSource, FrameSourceError
from src.camera.models import CapturedFrame
```

`TrackingBatch` import 바로 아래(클래스 정의 위)에 type alias 추가:

```python
from src.tracking.models import TrackingBatch
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import TrackingError

FrameObserver = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], None]
```

`process_next_frame()`을 다음으로 교체:

```python
    def process_next_frame(
        self, *, frame_observer: FrameObserver | None = None
    ) -> FrameObservationResult:
        """프레임 한 장을 캡처·추적하고 durable commit 결과를 반환한다.

        프레임 소진 시 `EndOfVideo`가, 그 외 캡처·추적 실패 시 각 계층의
        오류(`FrameSourceError`/`TrackingError`)가 그대로 전파된다 — 호출부가
        판단할 문제다.

        `frame_observer`는 commit이 성공한 뒤에만 `(frame, tracking_batch,
        result)`로 호출되는 선택적 telemetry·overlay 훅이다(`result_consumer`와
        같은 정책 — 예외를 숨기지 않고, durable 저장 책임을 갖지 않는다).
        `_commit_interruption` 경로(카메라·추적 장애)는 신뢰할 수 있는
        frame/tracking_batch가 없으므로 호출하지 않는다.
        """

        try:
            frame = self._frame_source.capture()
        except EndOfVideo:
            raise
        except FrameSourceError as error:
            self._commit_interruption(
                observed_at=error.observed_at,
                observation=error.observation,
            )
            raise

        try:
            tracking_batch = self._tracking_pipeline.process(
                frame,
                # 현재 고정 camera 파일럿은 FrameSource가 full frame을
                # 생성한다는 전제에서 calibration 좌표계를 최종
                # 인증한다. crop·camera health 검증은 기동 계층의 책임이다.
                full_area_observed=(
                    frame.calibration_id == self._calibration_reference
                ),
            )
        except TrackingError:
            self._commit_interruption(
                observed_at=frame.captured_at,
                observation=ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.PIPELINE_STALLED,
                ),
            )
            raise

        result = self._commit_batch(tracking_batch)
        if frame_observer is not None:
            frame_observer(frame, tracking_batch, result)
        return result
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py::test_process_next_frame_calls_frame_observer_after_commit -v`
Expected: PASS

- [ ] **Step 5: 실패하는 테스트 작성 — 에러 경로는 관측자를 호출하지 않는다**

`test_monitoring_pipeline.py`에 추가:

```python
def test_process_next_frame_skips_observer_when_capture_fails() -> None:
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FailingFrameSource([]), tracking, workflow)
    observed: list[tuple] = []

    with pytest.raises(FrameSourceError, match="camera unavailable"):
        pipeline.process_next_frame(
            frame_observer=lambda f, batch, r: observed.append((f, batch, r))
        )

    assert observed == []


def test_process_next_frame_skips_observer_when_tracking_fails() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1", captured_at=OBSERVED_AT)
    tracking = _TrackingPipeline(process_error=TrackingError("inference failed"))
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FrameSource([frame]), tracking, workflow)
    observed: list[tuple] = []

    with pytest.raises(TrackingError, match="inference failed"):
        pipeline.process_next_frame(
            frame_observer=lambda f, batch, r: observed.append((f, batch, r))
        )

    assert observed == []
```

- [ ] **Step 6: 테스트 실행해 통과 확인 (회귀 안전망)**

Step 3의 `try/except` 배치상 에러 경로는 `raise`로 끝나 `frame_observer` 호출 줄에 도달하지 않으므로, 이 두 테스트는 별도 구현 변경 없이 바로 통과해야 한다 — Step 3 구현이 에러 경로를 올바르게 건너뛰는지 지금 확인하고, 이후 리팩토링이 이 경계를 깨면 바로 잡아내는 회귀 테스트로 남긴다.

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py::test_process_next_frame_skips_observer_when_capture_fails tests/application/test_monitoring_pipeline.py::test_process_next_frame_skips_observer_when_tracking_fails -v`
Expected: PASS. FAIL이면(예: 관측자가 잘못 호출됨) Step 3의 `try/except` 배치를 다시 확인한다.

- [ ] **Step 7: 실패하는 테스트 작성 — `run()`이 매 프레임 관측자를 전달한다**

`test_monitoring_pipeline.py`에 추가:

```python
def test_run_threads_frame_observer_into_every_frame() -> None:
    frames = [
        SimpleNamespace(calibration_id="pilot-v1"),
        SimpleNamespace(calibration_id="other"),
    ]
    frame_source = _FrameSource(frames)
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)
    observed: list[tuple] = []

    frame_count = pipeline.run(
        frame_observer=lambda f, batch, r: observed.append((f, batch, r))
    )

    assert frame_count == 2
    assert [entry[0] for entry in observed] == frames
    assert [entry[2] for entry in observed] == workflow.results
```

- [ ] **Step 8: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py::test_run_threads_frame_observer_into_every_frame -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'frame_observer'`

- [ ] **Step 9: `run()`에 `frame_observer` 파라미터 구현**

`run()`을 다음으로 교체:

```python
    def run(
        self,
        *,
        result_consumer: Callable[[FrameObservationResult], None] | None = None,
        frame_observer: FrameObserver | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        """durable frame을 소스 소진 또는 종료 요청까지 처리한다.

        optional consumer는 commit 후 telemetry·overlay용이며 durable
        저장 책임을 갖지 않는다. consumer 예외는 숨기지 않는다.
        종료 요청은 frame 경계에서만 확인해 capture·model을 다른
        thread에서 동시에 close하지 않는다.

        `frame_observer`는 매 `process_next_frame()` 호출에 그대로
        전달된다 — `process_next_frame`의 `frame_observer` docstring과
        같은 정책(정상 커밋 후에만 호출, 예외 비은닉)을 따른다.
        """

        frames = 0
        should_stop = stop_requested or (lambda: False)
        while not should_stop():
            try:
                result = self.process_next_frame(frame_observer=frame_observer)
            except EndOfVideo:
                break
            if result_consumer is not None:
                result_consumer(result)
            frames += 1
        return frames
```

- [ ] **Step 10: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py::test_run_threads_frame_observer_into_every_frame -v`
Expected: PASS

- [ ] **Step 11: 전체 회귀 테스트 실행**

Run: `cd hw/jetson && python -m pytest tests/application/test_monitoring_pipeline.py -v`
Expected: 모든 테스트(기존 9개 + 새로 추가한 5개) PASS. 기존 테스트가 하나라도 깨지면 하위호환 위반이므로 구현을 다시 확인한다.

Run: `cd hw/jetson && python -m pytest tests/ -v`
Expected: 전체 스위트 PASS (numpy 미설치 환경이면 `pytest.importorskip("numpy")`로 관련 모듈만 skip — 이는 기존에도 마찬가지였던 동작이라 회귀 아님).

- [ ] **Step 12: 커밋**

```bash
cd hw/jetson
git add src/application/monitoring_pipeline.py tests/application/test_monitoring_pipeline.py
git commit -m "$(cat <<'EOF'
feat(ai): MonitoringPipeline에 frame_observer 콜백 추가

라이브 데모 오버레이가 판정용 추론을 다시 돌리지 않고 같은 1회
추론 결과(frame, tracking_batch, result)를 그대로 그릴 수 있도록
process_next_frame()/run()에 선택적 관측자 훅을 추가한다.
콜백 미전달 시 기존 replay 경로는 그대로 동작한다.

477
EOF
)"
```

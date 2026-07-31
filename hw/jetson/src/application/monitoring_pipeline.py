"""카메라·추적·주차 판정·전송 계층을 조립하는 애플리케이션 파이프라인(440).

관통 1단계 조립만 담당한다 — 실행 순서와 오류 경계는 여기서 관리하지만,
bbox 거리 계산이나 위반 조건 판단은 하지 않는다(데이터흐름.md §6
"application은 조립 담당이지 판정 담당이 아니다").

`TrackingPipeline`이 이미 `ContextMatcher`(T-16)로 `context`를 채워서
돌려준다(데이터흐름.md §2 — "입차 세션과 물리 차량 연결"은 tracking 자신의
책임) — 여기서는 그 배치를 그대로 parking에 넘긴다.

카메라 장애(source_available=False 처리)는 아직 다루지 않는다 — 실카메라
입력(웹캠 티켓)과 함께 결정할 사안이라 지금은 `FrameSourceError`를 그대로
전파한다. `EndOfVideo`(영상 리플레이 정상 종료)만 `run()`에서 조용히 멈추는
신호로 다룬다 — `ai/tracking/replay_pilot_video.py`의 기존 루프와 같은 패턴이다.
"""

from __future__ import annotations

from src.camera.frame_source import EndOfVideo, FrameSource
from src.communication.outbox import JsonlOutbox
from src.parking.models import ParkingPipelineResult
from src.parking.pipeline import ParkingPipeline
from src.tracking.pipeline import TrackingPipeline


class MonitoringPipeline:
    """camera → tracking → parking → outbox를 조립해 프레임 단위로 처리한다."""

    def __init__(
        self,
        *,
        frame_source: FrameSource,
        tracking_pipeline: TrackingPipeline,
        parking_pipeline: ParkingPipeline,
        outbox: JsonlOutbox,
    ) -> None:
        self._frame_source = frame_source
        self._tracking_pipeline = tracking_pipeline
        self._parking_pipeline = parking_pipeline
        self._outbox = outbox

    def open(self) -> None:
        """프레임 소스와 추적 모델을 초기화한다."""

        self._frame_source.open()
        self._tracking_pipeline.open()

    def process_next_frame(self) -> ParkingPipelineResult:
        """프레임 한 장을 캡처·추적·판정하고, 새 사건 전이를 outbox에 기록한다.

        프레임 소진 시 `EndOfVideo`가, 그 외 캡처·추적 실패 시 각 계층의
        오류(`FrameSourceError`/`TrackingError`)가 그대로 전파된다 — 호출부가
        판단할 문제다.
        """

        frame = self._frame_source.capture()
        tracking_batch = self._tracking_pipeline.process(frame)
        result = self._parking_pipeline.process(tracking_batch)
        for transition in result.incident_transitions:
            self._outbox.append(transition)
        return result

    def run(self) -> int:
        """프레임 소스가 소진될 때까지 반복 처리한다. 처리한 프레임 수를 반환한다."""

        frames = 0
        while True:
            try:
                self.process_next_frame()
            except EndOfVideo:
                break
            frames += 1
        return frames

    def close(self) -> None:
        """프레임 소스와 추적 모델 자원을 해제한다."""

        self._frame_source.close()
        self._tracking_pipeline.close()

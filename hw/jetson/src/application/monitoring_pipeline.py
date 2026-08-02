"""카메라·추적·주차 판정·전송 계층을 조립하는 애플리케이션 파이프라인.

실행 순서와 오류 경계만 관리하며 bbox 기하 계산이나
위반 조건 판단은 각 domain 계층에 맡긴다.

`TrackingPipeline`은 임시 TrackSegment, PhysicalVehicle 관측과 부재 신호만
만든다. SessionContext 매칭과 ContextBinding은 session coordinator가 소유하며
tracking snapshot에 복사하지 않는다. 현재 이 조립기에 session transaction을
연결하는 것은 후속 wiring 범위다.

프레임 캡처나 추론이 실패하면 부재 누적 연속성을 먼저 끊고
원래 예외를 전파한다. 그렇지 않으면 다음 정상 frame이 장애 구간의
wall-clock을 NOT_PRESENT 확정 시간에 포함한다. `EndOfVideo`는 리플레이
정상 종료이므로 `run()`에서만 조용히 멈춘다.
"""

from __future__ import annotations

from src.camera.frame_source import EndOfVideo, FrameSource, FrameSourceError
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
        calibration_reference: str,
    ) -> None:
        if not calibration_reference:
            raise ValueError("calibration_reference must not be empty")
        self._frame_source = frame_source
        self._tracking_pipeline = tracking_pipeline
        self._parking_pipeline = parking_pipeline
        self._outbox = outbox
        self._calibration_reference = calibration_reference

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

        try:
            frame = self._frame_source.capture()
        except EndOfVideo:
            raise
        except FrameSourceError:
            self._tracking_pipeline.pause_absence_confirmation()
            raise

        tracking_batch = self._tracking_pipeline.process(
            frame,
            # 현재 고정 camera 파일럿은 FrameSource가 full frame을
            # 생성한다는 전제에서 calibration 좌표계를 최종
            # 인증한다. crop·camera health 검증은 기동 계층의 책임이다.
            full_area_observed=(
                frame.calibration_id == self._calibration_reference
            ),
        )
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

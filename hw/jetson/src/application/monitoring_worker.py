"""MonitoringPipeline의 process-local 시작·종료 생명주기를 관리한다.

FastAPI request worker와 camera·model owner를 한 process에서 함께 실행하되,
model owner는 딱 하나의 thread만 가진다. 이 모듈은 pipeline을 조립하거나
실패를 domain 상태로 바꾸지 않고, 자원 생명주기와 운영 진단만 소유한다.
"""

from __future__ import annotations

import logging
from threading import Event, Thread

from src.application.monitoring_pipeline import FrameObserver, MonitoringPipeline


logger = logging.getLogger(__name__)


class MonitoringWorker:
    """카메라·model pipeline을 하나의 background thread에서 실행한다.

    ``start()``는 model·camera open이 성공한 후에만 복귀하므로 기동
    실패를 API readiness로 숨기지 않는다. ``stop()``은 새 frame 시작을
    막고 진행 중인 frame의 transaction이 끝난 뒤 자원 정리를 기다린다.

    ``frame_observer``는 그대로 ``pipeline.run()``에 전달만 한다 — 이
    worker는 관측 내용을 해석하지 않는다. 콜백이 예외를 던지면
    ``_run()``이 이를 치명 오류로 처리해 카메라·모델을 닫으므로, 예외
    흡수 책임은 콜백 구현체에 있다.
    """

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

    @property
    def failure(self) -> Exception | None:
        """Background loop가 예기치 않게 종료된 원인을 반환한다."""

        return self._failure

    @property
    def is_running(self) -> bool:
        """Monitoring loop thread가 현재 실행 중인지 반환한다."""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Durable 복구·camera·model을 열고 loop thread를 시작한다."""

        if self._thread is not None:
            raise RuntimeError("monitoring worker may only be started once")

        self._pipeline.open()
        thread = Thread(
            target=self._run,
            name="jetson-monitoring",
            daemon=False,
        )
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self._pipeline.close()
            raise

    def stop(self) -> None:
        """신규 frame 처리를 멈추고 worker의 자원 정리까지 기다린다."""

        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        try:
            self._pipeline.run(
                stop_requested=self._stop_requested.is_set,
                frame_observer=self._frame_observer,
            )
        except Exception as error:
            self._failure = error
            logger.exception("Jetson monitoring loop가 종료됐습니다.")
        finally:
            try:
                self._pipeline.close()
            except Exception as error:
                if self._failure is None:
                    self._failure = error
                logger.exception("Jetson monitoring 자원 정리에 실패했습니다.")

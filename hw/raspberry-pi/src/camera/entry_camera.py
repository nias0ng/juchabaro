"""
Picamera2를 사용해 입차 차량의 OCR 입력 프레임을 촬영한다.

카메라는 서비스 시작 시 한 번 초기화한 뒤 촬영 이벤트마다 재사용한다.
촬영 결과는 파일로 저장하지 않고 BGR uint8 배열을 가진 CapturedFrame으로
반환한다. 입차 판단, OCR 실행, 이벤트 시간과 외부 통신은 담당하지 않는다.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from src.config.settings import (
    CAMERA_HEIGHT,
    CAMERA_PIXEL_FORMAT,
    CAMERA_WARMUP_SECONDS,
    CAMERA_WIDTH,
    CAPTURE_FRAME_COUNT,
    CAPTURE_INTERVAL_SECONDS,
    CAPTURE_RETRY_COUNT,
    CAPTURE_RETRY_DELAY_SECONDS,
    CAPTURE_START_DELAY_SECONDS,
)
from src.ocr.types import BgrImage, CapturedFrame


# [카메라 예외]


class CameraError(RuntimeError):
    """카메라 초기화, 촬영 또는 자원 정리 과정의 기본 예외."""


class CameraInitializationError(CameraError):
    """카메라를 촬영 가능한 상태로 초기화하지 못한 경우."""


class FrameCaptureError(CameraError):
    """개별 프레임을 촬영하거나 이미지 계약을 검증하지 못한 경우."""


class CaptureSequenceError(CameraError):
    """모든 촬영 시도가 실패해 완전한 프레임 묶음을 얻지 못한 경우."""


# [기본 카메라 생성]


def create_picamera2() -> Any:
    """
    Picamera2를 지연 import하여 실제 카메라 객체를 생성한다.

    Picamera2가 설치되지 않은 개발 환경에서도 이 모듈 자체는 import할 수
    있으며, 기본 factory를 실제로 호출한 경우에만 Picamera2가 필요하다.
    """

    from picamera2 import Picamera2

    return Picamera2()


# [입차 카메라]


class EntryCamera:
    """
    Picamera2를 재사용해 입차 차량의 6프레임 촬영 묶음을 생성한다.

    생성 시 카메라를 구성하고 시작한 뒤 한 번만 warm-up한다. 촬영 묶음에
    프레임 실패가 하나라도 있으면 부분 결과를 폐기하고 전체를 재촬영한다.
    """

    def __init__(
        self,
        camera_factory: Callable[[], Any] = create_picamera2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._camera_factory = camera_factory
        self._sleep = sleep

        self._camera: Any | None = None
        self._started = False
        self._ready = False
        self._cleaned = False
        self._close_completed = False

        self._validate_settings()

        try:
            self._initialize_camera()
        except BaseException as exc:
            cleanup_failure = self._cleanup_after_initialization_failure()

            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise

            message = "입차 카메라 초기화에 실패했습니다."
            if cleanup_failure is not None:
                message += " 초기화 실패 후 카메라 자원 정리도 실패했습니다."

            raise CameraInitializationError(message) from exc

    @staticmethod
    def _validate_settings() -> None:
        """카메라 구성과 촬영 정책 설정값의 타입 및 범위를 검증한다."""

        for name, value in (
            ("CAMERA_WIDTH", CAMERA_WIDTH),
            ("CAMERA_HEIGHT", CAMERA_HEIGHT),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"{name}는 양의 정수여야 합니다.")

        if (
            isinstance(CAPTURE_FRAME_COUNT, bool)
            or not isinstance(CAPTURE_FRAME_COUNT, int)
            or CAPTURE_FRAME_COUNT != 6
        ):
            raise ValueError("CAPTURE_FRAME_COUNT는 정확히 6이어야 합니다.")

        if (
            isinstance(CAPTURE_RETRY_COUNT, bool)
            or not isinstance(CAPTURE_RETRY_COUNT, int)
            or CAPTURE_RETRY_COUNT < 0
        ):
            raise ValueError(
                "CAPTURE_RETRY_COUNT는 0 이상의 정수여야 합니다."
            )

        for name, value in (
            ("CAMERA_WARMUP_SECONDS", CAMERA_WARMUP_SECONDS),
            (
                "CAPTURE_START_DELAY_SECONDS",
                CAPTURE_START_DELAY_SECONDS,
            ),
            ("CAPTURE_INTERVAL_SECONDS", CAPTURE_INTERVAL_SECONDS),
            (
                "CAPTURE_RETRY_DELAY_SECONDS",
                CAPTURE_RETRY_DELAY_SECONDS,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"{name}는 0 이상의 유한한 수여야 합니다."
                )

        if (
            not isinstance(CAMERA_PIXEL_FORMAT, str)
            or not CAMERA_PIXEL_FORMAT.strip()
        ):
            raise ValueError(
                "CAMERA_PIXEL_FORMAT은 비어 있지 않은 문자열이어야 합니다."
            )

    def _initialize_camera(self) -> None:
        """카메라 객체를 생성하고 still stream을 촬영 가능한 상태로 만든다."""

        camera = self._camera_factory()
        if camera is None:
            raise CameraInitializationError(
                "camera factory가 카메라 객체를 반환하지 않았습니다."
            )

        self._camera = camera

        configuration = camera.create_still_configuration(
            main={
                "size": (CAMERA_WIDTH, CAMERA_HEIGHT),
                "format": CAMERA_PIXEL_FORMAT,
            }
        )
        camera.configure(configuration)
        camera.start()

        self._started = True
        self._sleep(CAMERA_WARMUP_SECONDS)
        self._ready = True

    def capture_sequence(self) -> tuple[CapturedFrame, ...]:
        """
        입차 촬영 지연 후 완전한 6프레임 묶음을 반환한다.

        최초 촬영 전에 start delay를 한 번만 적용한다. 프레임 하나라도
        실패하면 해당 시도의 부분 결과를 폐기하고 retry delay 후 동일한
        카메라 객체로 전체 촬영을 다시 수행한다.

        모든 시도가 실패하면 마지막 FrameCaptureError를 원인으로 갖는
        CaptureSequenceError를 발생시킨다.
        """

        self._require_ready()
        self._sleep(CAPTURE_START_DELAY_SECONDS)

        failures: list[FrameCaptureError] = []
        total_attempts = CAPTURE_RETRY_COUNT + 1

        for attempt_index in range(total_attempts):
            try:
                return self._capture_once()
            except FrameCaptureError as exc:
                failures.append(exc)

            if attempt_index < total_attempts - 1:
                self._sleep(CAPTURE_RETRY_DELAY_SECONDS)

        failure_messages = "; ".join(
            f"시도 {index + 1}: {failure}"
            for index, failure in enumerate(failures)
        )
        message = (
            f"총 {total_attempts}회의 전체 촬영 시도가 실패했습니다."
        )
        if failure_messages:
            message += f" {failure_messages}"

        raise CaptureSequenceError(message) from failures[-1]

    def _capture_once(self) -> tuple[CapturedFrame, ...]:
        """
        프레임 인덱스 0부터 시작해 정확히 한 묶음을 촬영한다.

        마지막 프레임을 제외한 각 촬영 뒤에만 프레임 간격을 적용한다.
        프레임 촬영 또는 대기 중 일반 예외가 발생하면 부분 결과를 반환하지
        않고 FrameCaptureError를 발생시킨다.
        """

        frames: list[CapturedFrame] = []

        for frame_index in range(CAPTURE_FRAME_COUNT):
            frames.append(self._capture_frame(frame_index))

            if frame_index < CAPTURE_FRAME_COUNT - 1:
                try:
                    self._sleep(CAPTURE_INTERVAL_SECONDS)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    raise FrameCaptureError(
                        "frame_index="
                        f"{frame_index}: 다음 프레임 촬영 전 대기에 "
                        "실패했습니다."
                    ) from exc

        return tuple(frames)

    def _capture_frame(self, frame_index: int) -> CapturedFrame:
        """
        main stream의 RGB 프레임 하나를 독립적인 BGR 배열로 변환한다.

        카메라 API 오류, 잘못된 배열 또는 변환·복사 실패는 실패한
        frame_index를 포함하는 FrameCaptureError로 변환한다.
        """

        self._require_ready()
        camera = self._camera

        try:
            rgb_image = camera.capture_array("main")
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라 촬영에 실패했습니다."
            ) from exc

        try:
            self._validate_rgb_image(
                rgb_image,
                frame_index=frame_index,
            )
            bgr_image: BgrImage = rgb_image[:, :, ::-1].copy()
        except (KeyboardInterrupt, SystemExit):
            raise
        except FrameCaptureError:
            raise
        except Exception as exc:
            raise FrameCaptureError(
                f"frame_index={frame_index}: RGB 이미지를 독립적인 "
                "BGR 배열로 변환하지 못했습니다."
            ) from exc

        return CapturedFrame(
            frame_index=frame_index,
            image=bgr_image,
        )

    @staticmethod
    def _validate_rgb_image(
        image: Any,
        *,
        frame_index: int,
    ) -> None:
        """Picamera2 결과가 확정된 RGB 이미지 계약을 만족하는지 검증한다."""

        if image is None:
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라가 이미지를 "
                "반환하지 않았습니다."
            )

        if not isinstance(image, np.ndarray):
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라 결과는 "
                "numpy.ndarray여야 합니다."
            )

        if image.size == 0:
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라 결과가 비어 있습니다."
            )

        if image.dtype != np.uint8:
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라 결과의 dtype은 "
                "numpy.uint8이어야 합니다."
            )

        expected_shape = (
            CAMERA_HEIGHT,
            CAMERA_WIDTH,
            3,
        )
        if image.shape != expected_shape:
            raise FrameCaptureError(
                f"frame_index={frame_index}: 카메라 결과 shape이 "
                f"{expected_shape}이어야 합니다."
            )

    def _require_ready(self) -> None:
        """현재 객체가 촬영 가능한 상태인지 확인한다."""

        if self._cleaned:
            raise CameraError("이미 정리된 카메라는 다시 사용할 수 없습니다.")

        if (
            self._camera is None
            or not self._started
            or not self._ready
        ):
            raise CameraError("카메라가 촬영 가능한 상태가 아닙니다.")

    def cleanup(self) -> None:
        """
        카메라 stream을 중지하고 장치 자원을 해제한다.

        stop 실패 여부와 관계없이 close를 시도한다. close가 성공하면 최종
        자원 해제로 간주하며, stop 실패가 있더라도 cleanup 완료 상태를
        확정한 뒤 해당 오류를 전달한다. close가 실패한 경우에만 다음
        cleanup 호출에서 완료되지 않은 작업을 재시도한다.
        """

        if self._cleaned:
            return

        self._ready = False

        if self._close_completed:
            self._started = False
            self._camera = None
            self._cleaned = True
            return

        camera = self._camera
        if camera is None:
            self._started = False
            self._close_completed = True
            self._cleaned = True
            return

        failures: list[BaseException] = []

        if self._started:
            try:
                camera.stop()
            except BaseException as exc:
                failures.append(exc)
            else:
                self._started = False

        try:
            camera.close()
        except BaseException as exc:
            failures.append(exc)
        else:
            # close 성공을 최종 자원 해제 기준으로 삼는다.
            self._started = False
            self._close_completed = True
            self._camera = None
            self._cleaned = True

        termination_failure = next(
            (
                failure
                for failure in failures
                if isinstance(failure, (KeyboardInterrupt, SystemExit))
            ),
            None,
        )
        if termination_failure is not None:
            raise termination_failure

        if failures:
            action = (
                "중지와 해제"
                if len(failures) > 1
                else "중지 또는 해제"
            )
            raise CameraError(
                f"카메라 {action}에 실패했습니다."
            ) from failures[0]

    def _cleanup_after_initialization_failure(
        self,
    ) -> BaseException | None:
        """
        부분 초기화된 카메라 자원을 정리하고 정리 실패를 반환한다.

        초기화의 원래 실패가 정리 예외에 의해 가려지지 않도록 cleanup
        예외를 호출자에게 반환한다.
        """

        try:
            self.cleanup()
        except BaseException as exc:
            return exc

        return None

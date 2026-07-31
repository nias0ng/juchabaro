"""
Raspberry Pi 입차 감지 서비스의 객체 생명주기와 실행 흐름을 관리한다.

초음파 센서 측정값으로 입차 확정 신호를 확인하고 해당 시점에 카메라
촬영을 실행한다. 입차 판단 세부 로직, 카메라 내부 제어, OCR 처리와 외부
통신은 담당하지 않는다.
"""

import logging
import math
import time

from src.camera.entry_camera import (
    CameraInitializationError,
    CaptureSequenceError,
    EntryCamera,
)
from src.config.settings import MEASUREMENT_INTERVAL_SECONDS
from src.entry.entry_controller import EntryController, EntrySignal
from src.sensors.ultrasonic_sensor import UltrasonicSensor


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def validate_measurement_interval() -> None:
    if (
        isinstance(MEASUREMENT_INTERVAL_SECONDS, bool)
        or not isinstance(MEASUREMENT_INTERVAL_SECONDS, (int, float))
        or not math.isfinite(MEASUREMENT_INTERVAL_SECONDS)
        or MEASUREMENT_INTERVAL_SECONDS <= 0
    ):
        raise ValueError("측정 주기는 0보다 큰 유한한 수여야 합니다.")


def main() -> None:
    configure_logging()
    validate_measurement_interval()

    logger = logging.getLogger(__name__)
    controller = EntryController()
    sensor: UltrasonicSensor | None = None
    camera: EntryCamera | None = None
    service_started = False

    try:
        sensor = UltrasonicSensor()

        try:
            camera = EntryCamera()
        except (CameraInitializationError, ValueError):
            logger.exception("Raspberry Pi entry camera initialization failed.")
            raise

        logger.info("Raspberry Pi entry service started.")
        service_started = True

        try:
            while True:
                distance_cm = sensor.measure()
                signal = controller.update(distance_cm)

                if signal is EntrySignal.ENTRY_DETECTED:
                    logger.info("Vehicle entry detected.")

                    try:
                        frames = camera.capture_sequence()
                    except CaptureSequenceError:
                        logger.warning(
                            "Vehicle entry capture failed.",
                            exc_info=True,
                        )
                    else:
                        logger.info(
                            "Vehicle entry capture succeeded. frame_count=%s",
                            len(frames),
                        )

                time.sleep(MEASUREMENT_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            pass
    finally:
        cleanup_termination: KeyboardInterrupt | SystemExit | None = None

        if camera is not None:
            try:
                camera.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                cleanup_termination = exc
            except Exception:
                logger.exception(
                    "Raspberry Pi entry camera cleanup failed."
                )

        if sensor is not None:
            try:
                sensor.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                if cleanup_termination is None:
                    cleanup_termination = exc
            except Exception:
                logger.exception(
                    "Raspberry Pi ultrasonic sensor cleanup failed."
                )

        if service_started:
            logger.info("Raspberry Pi entry service stopped.")

        if cleanup_termination is not None:
            raise cleanup_termination


if __name__ == "__main__":
    main()

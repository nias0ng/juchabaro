import logging
import math
import time

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
    sensor = UltrasonicSensor()

    logger.info("Raspberry Pi entry service started.")

    try:
        while True:
            distance_cm = sensor.measure()
            signal = controller.update(distance_cm)

            if signal is EntrySignal.ENTRY_DETECTED:
                logger.info("Vehicle entry detected.")

            time.sleep(MEASUREMENT_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.cleanup()
        logger.info("Raspberry Pi entry service stopped.")


if __name__ == "__main__":
    main()

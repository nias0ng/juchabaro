import time

from src.config.settings import MEASUREMENT_INTERVAL_SECONDS
from src.sensors.ultrasonic_sensor import UltrasonicSensor


def main() -> None:
    sensor = UltrasonicSensor()

    try:
        while True:
            distance_cm = sensor.measure()

            if distance_cm is None:
                print("Distance: None")
            else:
                print(f"Distance: {distance_cm:.2f} cm")

            time.sleep(MEASUREMENT_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        sensor.cleanup()


if __name__ == "__main__":
    main()

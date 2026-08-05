from src.config.settings import GREEN_LED_DURATION_SECONDS
from src.indicators.green_led import GreenLed


def main() -> None:
    led = GreenLed()

    try:
        print(
            "Green LED check started: "
            f"ON for {GREEN_LED_DURATION_SECONDS:.1f} seconds."
        )
        led.indicate_allow(GREEN_LED_DURATION_SECONDS)
        print("Green LED check completed.")
    finally:
        led.cleanup()


if __name__ == "__main__":
    main()

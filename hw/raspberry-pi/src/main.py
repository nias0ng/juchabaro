import logging


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    configure_logging()

    logger = logging.getLogger(__name__)
    logger.info("Raspberry Pi entry service started.")


if __name__ == "__main__":
    main()
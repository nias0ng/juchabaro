import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH)

# [환경 변수]
BACKEND_BASE_URL: Final[str] = os.getenv("BACKEND_BASE_URL", "")
BACKEND_HW_API_KEY: Final[str] = os.getenv("BACKEND_HW_API_KEY", "")

# [GPIO 설정]

GPIO_MODE: Final[str] = "BCM"

TRIGGER_PIN: Final[int] = 23  # BCM GPIO23 -> 물리 핀 16
ECHO_PIN: Final[int] = 24  # BCM GPIO24 -> 물리 핀 18


# [LED 설정]

GREEN_LED_PIN: Final[int] = 17  # BCM GPIO17 -> 물리 핀 11
GREEN_LED_ACTIVE_HIGH: Final[bool] = True

# 프로토타입 입차 흐름 검증 후 실제 운영 환경에 맞게 재조정
GREEN_LED_DURATION_SECONDS: Final[float] = 3.0


# [초음파 센서 측정 설정]

TRIGGER_PULSE_SECONDS: Final[float] = 0.00001
STABILIZATION_SECONDS: Final[float] = 0.1

# 실제 센서 응답과 GPIO 스케줄링 지연에 따라 조정 가능
ECHO_TIMEOUT_SECONDS: Final[float] = 0.005

MEASUREMENT_INTERVAL_SECONDS: Final[float] = 0.1

SOUND_SPEED_CM_PER_SECOND: Final[float] = 34300.0

MIN_VALID_DISTANCE_CM: Final[float] = 2.0

# 설치 구조에서 발생할 수 있는 최대 측정 거리를 고려해 조정
MAX_VALID_DISTANCE_CM: Final[float] = 30.0


# [입차 판단 설정]

# 실제 차량 위치와 센서 측정 결과에 따라 조정
ENTRY_DISTANCE_THRESHOLD_CM: Final[float] = 6.0
RELEASE_DISTANCE_THRESHOLD_CM: Final[float] = 10.0

REQUIRED_DETECTION_COUNT: Final[int] = 3
REQUIRED_RELEASE_COUNT: Final[int] = 3


# [카메라 설정]

CAMERA_WIDTH: Final[int] = 1280
CAMERA_HEIGHT: Final[int] = 720

# Picamera2의 RGB888 capture_array 결과는 NumPy에서 BGR 순서다.
CAMERA_PIXEL_FORMAT: Final[str] = "RGB888"

CAMERA_WARMUP_SECONDS: Final[float] = 2.0

CAPTURE_FRAME_COUNT: Final[int] = 6

# 실제 차량 촬영 테스트 후 재조정이 필요한 초기값
CAPTURE_START_DELAY_SECONDS: Final[float] = 0.5
CAPTURE_INTERVAL_SECONDS: Final[float] = 0.1
CAPTURE_RETRY_DELAY_SECONDS: Final[float] = 0.2

# 최초 촬영 실패 후 수행할 전체 재촬영 횟수
CAPTURE_RETRY_COUNT: Final[int] = 1


# [OCR 설정]

OCR_DETECTOR_MODEL_PATH: Final[Path] = Path(
    "/home/e202/models/plate_detector/bestv1_1.pt"
)
OCR_RECOGNIZER_MODEL_DIR: Final[Path] = Path(
    "/home/e202/models/plate_recognizer"
)

OCR_DEVICE: Final[str] = "cpu"
OCR_WARMUP_ENABLED: Final[bool] = True

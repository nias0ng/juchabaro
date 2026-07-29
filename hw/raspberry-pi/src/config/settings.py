from typing import Final


GPIO_MODE: Final[str] = "BCM"

TRIGGER_PIN: Final[int] = 23  # BCM GPIO23 -> 물리 핀 16
ECHO_PIN: Final[int] = 24  # BCM GPIO24 -> 물리 핀 18

TRIGGER_PULSE_SECONDS: Final[float] = 0.00001  
STABILIZATION_SECONDS: Final[float] = 0.1  

# 실제 센서 응답과 GPIO 스케줄링 지연에 따라 조정 가능
ECHO_TIMEOUT_SECONDS: Final[float] = 0.005

MEASUREMENT_INTERVAL_SECONDS: Final[float] = 0.1

SOUND_SPEED_CM_PER_SECOND: Final[float] = 34300.0  

MIN_VALID_DISTANCE_CM: Final[float] = 2.0  

# 설치 구조에서 발생할 수 있는 최대 측정 거리를 고려해 조정
MAX_VALID_DISTANCE_CM: Final[float] = 30.0

# 실제 차량 위치와 센서 측정 결과에 따라 조정 
ENTRY_DISTANCE_THRESHOLD_CM: Final[float] = 6.0
RELEASE_DISTANCE_THRESHOLD_CM: Final[float] = 10.0

REQUIRED_DETECTION_COUNT: Final[int] = 3
REQUIRED_RELEASE_COUNT: Final[int] = 3

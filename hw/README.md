# Smart Parking Hardware

스마트 주차장 시스템의 Raspberry Pi 및 Jetson Orin Nano 소스 코드를 관리한다.

## 장치 구성

### Raspberry Pi

주차장 입구의 차량 감지와 번호판 인식을 담당한다.

주요 기능:

- 초음파 센서를 이용한 입차 감지
- 입차 차량 번호판 촬영
- 번호판 OCR 수행
- OCR 결과를 Jetson으로 전송

Raspberry Pi는 일반 Python 장기 실행 프로그램으로 동작한다.

### Jetson Orin Nano

주차장 내부 영상 분석과 현장 장치 제어를 담당한다.

주요 기능:

- Raspberry Pi의 번호판 OCR 결과 수신
- 차량 객체 탐지
- 차량 추적 (ByteTrack)
- 번호판과 Tracking ID 매핑
- 주차 위치 및 주차 상태 판단
- 장애인·전기차 구역 센서 처리
- LED와 스피커 제어
- Spring Backend 통신
- Backend의 이동 여부 확인 요청 수신

Jetson은 FastAPI 서버로 동작한다.

## 통신 구조

```text
Raspberry Pi
    │
    │ 번호판 OCR 결과
    ▼
Jetson FastAPI
    │
    │ 차량 조회·입차·주차·사건 정보
    ▼
Spring Backend
```

## 디렉토리

### Raspberry Pi

| Directory | Description |
|-----------|-------------|
| `camera/` | 입차 카메라 촬영 |
| `communication/` | Jetson 통신 |
| `config/` | 환경 설정 |
| `entry/` | 입차 처리 흐름 |
| `ocr/` | 번호판 OCR |
| `sensors/` | 초음파 센서 처리 |
| `scripts/` | 장치별 수동 테스트 스크립트 |
| `tests/` | 자동 테스트 |

### Jetson

| Directory | Description |
|-----------|-------------|
| `api/` | Jetson이 제공하는 FastAPI |
| `actuators/` | LED 및 스피커 제어 |
| `camera/` | 천장 카메라 입력 |
| `communication/` | Raspberry Pi 및 Backend 통신 |
| `config/` | 환경 설정 |
| `parking/` | 주차 상태 및 주차 사건 판단 |
| `sensors/` | ToF 등 센서 처리 |
| `tracking/` | 차량 탐지 및 추적 |
| `scripts/` | 장치별 수동 테스트 스크립트 |
| `tests/` | 자동 테스트 |

## 식별자

- 식별자의 의미·수명·생성 책임을 변경하거나 연동할 때는
  [`docs/architecture/identifier-contract.md`](../docs/architecture/identifier-contract.md)를 먼저 확인한다.
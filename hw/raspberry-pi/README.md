# Raspberry Pi Entry Service

주차장 입구의 차량 감지, 번호판 촬영, OCR 및 Backend 입차 등록 요청을
담당한다.

## 실행 환경

- Python 3.13.5
- Debian GNU/Linux 13 (trixie)

## 목표 처리 흐름

1. 프로그램 실행
2. Backend 설정 검증
3. BackendClient 생성과 OCR pipeline 1회 로드
4. 초음파 센서로 차량 입차 감지
5. Raspberry Pi에서 입차 시도 정보 생성
6. `EntryCamera`로 번호판 6프레임 촬영
7. 촬영 프레임에서 번호판 OCR 수행
8. OCR 성공 시 Backend 입차 등록 API 호출
9. Backend로부터 `ALLOW`, `REVIEW`, `DENY` 판정과 입차 처리 결과 수신
10. Backend 응답을 기반으로 LED를 제어해 입차 가능 여부 표시
11. 필요한 입차 정보를 Jetson으로 전송
12. 다음 차량 입차 감지 대기

위 흐름은 프로젝트의 최종 목표다. 현재 구현 완료 범위와 아직 연결되지
않은 기능은 아래에서 구분한다.

## 현재 구현 범위

현재 `src.main`에는 초음파 센서 기반 차량 감지, 입차 시도 정보 생성,
6프레임 촬영, OCR pipeline 실행과 Backend 입차 등록 요청이 연결되어
있다.

서비스 시작 시 Backend 설정을 검증하고 `BackendClient`와 OCR pipeline을
각각 한 번 생성한다. OCR이 번호판을 확정한 경우에만 Backend 입차 등록
API를 호출하며, 응답의 `ALLOW`, `REVIEW`, `DENY` 판정을 로그로 기록한다.

현재 구현에는 LED 표시, Jetson 전송, 자동 재시도와 Backend
응답 영속 저장이 포함되어 있지 않다.

## Backend 입차 등록 연동

### 설정과 인증

다음 환경변수가 필요하다.

| 환경변수 | 설명 |
| --- | --- |
| `BACKEND_BASE_URL` | Backend API base URL |
| `BACKEND_HW_API_KEY` | Backend HW API 인증 key |

두 값이 비어 있거나 공백뿐이면 OCR pipeline, 센서와 카메라를 초기화하기
전에 실행을 중단한다. Raspberry Pi의 `BACKEND_HW_API_KEY`는 Backend에
설정된 HW API key와 일치해야 하며, 요청의 `X-HW-API-Key` header로
전달된다. API key 실제 값은 로그에 기록하지 않는다.

`.env.example`의 배포 환경 예시는 다음과 같다.

```text
BACKEND_BASE_URL=https://i15e202.p.ssafy.io/api/
BACKEND_HW_API_KEY=
```

입차 등록 endpoint는 다음과 같다.

```http
POST /hw/parking/entry
```

`BACKEND_BASE_URL`에 `/api` reverse proxy prefix가 포함된 위 예시의 최종
요청 URL은 다음과 같다.

```text
https://i15e202.p.ssafy.io/api/hw/parking/entry
```

Spring Boot에 직접 접근하는 로컬 환경에서는 `/api` prefix가 없는 base
URL을 사용할 수 있다.

### 입차 시도 식별자와 시각

차량 입차가 확정되면 촬영 전에 `EntryEvent`를 생성한다.

- `entry_attempt_id`: 한 번의 물리적 차량 입차 인식 시도를 식별하는 UUID
- `idempotency_key`: 해당 Backend 요청과 재전송을 식별하는 별도의 UUID
- `entry_time`: `+09:00` offset이 포함된 timezone-aware `datetime`

Python의 `entry_attempt_id`는 요청 body의 `entryAttemptId`로 직렬화된다.
이 값은 ByteTrack ID가 아니다.

`idempotency_key`는 `entryAttemptId`와 목적이 다르며 요청의
`Idempotency-Key` HTTP header로 전달된다. 동일 요청을 재전송할 때는
같은 key를 사용해야 하지만, 현재 Raspberry Pi 실행 흐름에는 자동
재시도가 구현되어 있지 않다.

입차 시각은 communication schema에서 offset이 포함된 ISO 8601 문자열로
직렬화된다. wire 필드명은 `entryTime`이다.

```json
{
  "entryTime": "2026-07-31T12:34:56+09:00"
}
```

`+09:00`은 UTC보다 9시간 빠른 timezone offset이다. ISO 8601 문자열을
사용한다는 것이 UTC timezone만 사용한다는 의미는 아니다.

### Backend 요청

OCR이 번호판을 확정한 경우 다음 body 필드를 전송한다.

```json
{
  "entryAttemptId": "550e8400-e29b-41d4-a716-446655440000",
  "recognizedPlateNumber": "12가3456",
  "ocrConfidence": 0.97,
  "entryTime": "2026-07-31T12:34:56+09:00"
}
```

OCR pipeline이 반환한 `PlateReadResult.rec_score`를 Backend 요청의
`ocrConfidence`로 전달한다. 이 값은 OCR 내부 판정의 `winner_rec_score`에서
가져온 대표 인식 점수이며, Raspberry Pi에서 별도로 계산하거나 보정하지
않는다.

```text
PlateDecision.winner_rec_score
→ PlateReadResult.rec_score
→ BackendEntryRequest.confidence
→ JSON의 ocrConfidence
```

### BackendClient 생명주기

`BackendClient`는 startup에서 한 번 생성되고 여러 입차 이벤트에서 같은
객체를 재사용한다. 요청은 동기 방식이며 기본 timeout은 5초다.

`BackendClient`에는 별도 cleanup API가 없다. 서비스 종료 시에는 기존과
같이 카메라를 먼저 정리하고 센서를 정리한다.

### Backend 응답과 오류 정책

정상 응답의 판정은 다음 로그 수준으로 기록한다.

| 판정 | 로그 수준 |
| --- | --- |
| `ALLOW` | info |
| `REVIEW` | warning |
| `DENY` | warning |

현재 구현은 판정을 로그로 기록하며 LED 또는 Jetson을 제어하지
않는다.

Backend 응답의 `entryAttemptId`가 요청 값과 다르면 예상하지 못한 계약
위반으로 `RuntimeError`를 전파한다. 이 경우 정상 판정 로그를 남기지
않는다.

`BackendClientError`는 연결 실패, timeout, HTTP 오류, 잘못된 JSON과
응답 계약 오류를 나타낸다. 이 오류는 현재 입차 이벤트의 실패로 기록하고
다음 센서 감지를 계속한다.

예상하지 못한 예외와 응답 ID 불일치는 상위로 전파한다. `main()`의
`finally`는 이 경우에도 카메라와 센서를 정리한다. 현재 자동 재시도는
구현되어 있지 않다.

## 설치 준비

`raspberry-pi` 폴더에서 현재 Raspberry Pi Python 실행 환경에 필요한
의존성을 설치한다.

```bash
python -m pip install -r requirements.txt
```

이 명령은 Python 의존성을 설치하며 Raspberry Pi 카메라의 전체 시스템
환경까지 구성하지는 않는다. `EntryCamera`는 실제 카메라 객체를 생성할
때 `picamera2`를 import하지만, Picamera2는 현재 `requirements.txt`에서
설치하지 않는다.

실제 Raspberry Pi에서 카메라를 사용하려면 Picamera2와 libcamera를
사용할 수 있는 시스템 환경이 별도로 준비되어 있어야 한다. 필요한
설치 방식과 OS 구성은 현재 저장소만으로 확정할 수 없으므로 Raspberry Pi
운영 이미지에서 확인해야 한다.

`requirements.txt`의 `rpi-lgpio`와 PyTorch wheel URL은 Raspberry Pi
OS의 CPython 3.13/AArch64 환경을 대상으로 한다. 따라서 Windows를
포함한 일반 PC에서는 `requirements.txt` 전체를 그대로 설치할 수 없다.

PC 단위 테스트에는 PC 플랫폼과 Python 버전에 맞는 별도 Python 환경과
pytest, python-dotenv, NumPy, OpenCV 계열 의존성이 필요하다. PC용 전체
설치 명령과 OpenCV package 선택 및 버전은 이 문서에서 별도로 정하지
않는다.

## 모델 다운로드

서비스를 처음 실행하기 전에 번호판 탐지 모델과 한국어 PaddleOCR ONNX
모델을 다운로드한다. 기본 설치 경로는 `/home/e202/models`이다.

```bash
python scripts/download_models.py
```

다른 경로에 설치하려면 `--models-dir`를 지정한다.

```bash
python scripts/download_models.py --models-dir ./models
```

스크립트는 다음 모델을 설치하고 SHA-256을 검증한다.

- `plate_detector/bestv1_1.pt`: Hugging Face 공개 저장소의 고정 커밋
- `plate_recognizer/inference.onnx`: `korean_PP-OCRv5_mobile_rec` ONNX 모델
- `plate_recognizer/inference.yml`: PaddleOCR recognition 설정

현재 서비스 설정은 기본 설치 경로를 사용한다. `--models-dir`로 다른
위치에 설치한 경우에는 `src/config/settings.py`의 detector와 recognizer
경로도 실제 설치 위치에 맞춰야 한다.

## OCR 실행 설정

현재 `src/config/settings.py`의 OCR 기본 설정은 다음과 같다.

| 설정 | 기본값 |
| --- | --- |
| `OCR_DETECTOR_MODEL_PATH` | `/home/e202/models/plate_detector/bestv1_1.pt` |
| `OCR_RECOGNIZER_MODEL_DIR` | `/home/e202/models/plate_recognizer` |
| `OCR_DEVICE` | `cpu` |
| `OCR_WARMUP_ENABLED` | `True` |
| `CAPTURE_FRAME_COUNT` | `6` |

`EntryCamera`는 `CAPTURE_FRAME_COUNT`에 따라 6프레임을 촬영한다.
`src.main`도 같은 설정값으로 `OcrPipelinePolicy.frame_count`를 구성해
카메라 출력과 OCR 입력의 burst 크기를 맞춘다. 카메라에 policy 객체를
직접 전달하거나 공유하지는 않는다.

## 실행

의존성과 모델을 준비한 뒤 `raspberry-pi` 폴더에서 실행한다.

```bash
python -m src.main
```

서비스 startup에서 모델 load 또는 warm-up이 실패하면 센서와 카메라를
생성하지 않고 실행을 중단한다.

## OCR pipeline 생명주기

`src.main`은 서비스 startup에서 `load_plate_ocr_pipeline()`을 정확히
한 번 호출한다. 반환된 pipeline은 `main()`이 종료될 때까지 보관하고,
입차 이벤트마다 같은 pipeline의 `read_plate(frames)`를 호출한다.

차량 이벤트마다 OCR 모델이나 pipeline을 다시 로드하지 않는다. 알려진
촬영 또는 OCR 이벤트 오류가 발생해도 pipeline을 교체하거나 다시
생성하지 않는다.

## OCR pipeline 공개 API

다음 코드는 현재 `src.main`의 OCR startup 구성과 입차 이벤트 호출
흐름을 축약해 보여준다. 센서 반복문과 전체 cleanup 코드는 생략했지만,
표시된 클래스와 함수는 실제 공개 API다.

```python
from src.camera.entry_camera import EntryCamera
from src.config.settings import (
    CAPTURE_FRAME_COUNT,
    OCR_DETECTOR_MODEL_PATH,
    OCR_DEVICE,
    OCR_RECOGNIZER_MODEL_DIR,
    OCR_WARMUP_ENABLED,
)
from src.ocr import (
    OcrPipelinePolicy,
    OcrRuntimeConfig,
    PlateReadResult,
    load_plate_ocr_pipeline,
)

policy = OcrPipelinePolicy(
    frame_count=CAPTURE_FRAME_COUNT,
)
ocr_pipeline = load_plate_ocr_pipeline(
    OcrRuntimeConfig(
        detector_model_path=OCR_DETECTOR_MODEL_PATH,
        recognizer_model_dir=OCR_RECOGNIZER_MODEL_DIR,
        policy=policy,
        device=OCR_DEVICE,
        warm_up=OCR_WARMUP_ENABLED,
    )
)

camera = EntryCamera()

try:
    # 입차 이벤트가 발생할 때마다 같은 camera와 pipeline을 사용한다.
    frames = camera.capture_sequence()
    result: PlateReadResult = ocr_pipeline.read_plate(frames)
finally:
    camera.cleanup()
```

실제 서비스에서는 startup에서 생성한 `EntryCamera`와 OCR pipeline을
반복해서 사용하고 서비스 종료 시 기존 lifecycle에 따라 카메라와 센서를
정리한다. OCR pipeline에는 별도의 cleanup API가 없다.

`EntryCamera.capture_sequence()`이 반환한 `tuple[CapturedFrame, ...]`은
별도 변환이나 복사 없이 `read_plate(frames)`에 전달된다.

## OCR 결과 및 오류 정책

`PlateOcrPipeline.read_plate()`는 `PlateReadResult`를 반환한다.

| 분류 | `ReadStatus` | 처리 |
| --- | --- | --- |
| 성공 | `SUCCESS` | 확정된 번호판을 info 로그로 기록 |
| 정상 판독 실패 | `NO_PLATE_REGION`, `OCR_EMPTY`, `INVALID_FORMAT` | warning 로그 후 다음 감지 대기 |
| 불확실 결과 | `LOW_SCORE`, `AMBIGUOUS` | 불확실 warning 로그 후 다음 감지 대기 |

현재 `src.main`은 OCR 결과를 다음과 같이 처리한다.

- 촬영 중 `CaptureSequenceError`가 발생하면 OCR을 호출하지 않고 다음 입차 감지를 기다린다.
- `InvalidBurstError`는 카메라와 OCR 사이의 입력 계약 오류로 기록한다.
- `OcrRuntimeError`는 모델, adapter 또는 OpenCV 실행 오류로 기록한다.
- 알려진 촬영 및 OCR 이벤트 오류는 해당 이벤트만 실패 처리하고 감지 루프를 계속한다.
- 모델 load 또는 warm-up 실패는 startup 실패로 전파한다.
- 공개 계약에 없는 상태와 예상하지 못한 예외는 정상적인 이벤트 실패로 숨기지 않는다.

Backend 입차 등록 API는 `ReadStatus.SUCCESS`이면서 확정된
`plate_number`와 대표 `rec_score`가 모두 존재할 때만 호출한다.

다음 상태에서는 Backend를 호출하지 않고 현재 이벤트를 종료한 뒤 다음
감지를 기다린다.

- `NO_PLATE_REGION`
- `OCR_EMPTY`
- `INVALID_FORMAT`
- `LOW_SCORE`
- `AMBIGUOUS`

다음 알려진 오류에서도 Backend를 호출하지 않는다.

- 촬영 중 `CaptureSequenceError`
- OCR 입력의 `InvalidBurstError`
- OCR 실행의 `OcrRuntimeError`

`SUCCESS`인데 확정된 번호판이나 대표 `rec_score`가 없으면 OCR 결과 계약
위반으로 `RuntimeError`를 전파하고 Backend를 호출하지 않는다. 공개 계약에
없는 OCR 상태와 그 밖의 예상하지 못한 예외도 정상적인 이벤트 실패로
숨기지 않는다.

하드웨어 초기화 이후 서비스가 종료되면 카메라를 먼저 정리하고 센서를
정리한다. 카메라 cleanup 실패는 센서 cleanup을 막지 않으며 cleanup 중
발생한 `KeyboardInterrupt`와 `SystemExit`도 보존한다.

## 테스트

전체 단위 테스트를 실행한다.

```bash
python -m pytest
```

`src.main`의 orchestration 흐름만 확인하려면 다음과 같이
실행한다.

```bash
python -m pytest tests/test_main.py
```

입차 시도 객체의 계약은 다음 테스트에서 검증한다.

```bash
python -m pytest tests/entry/test_entry_event.py
```

`tests/entry/test_entry_event.py`는 다음 항목을 검증한다.

- 입차 시도 객체의 불변성
- 식별자의 빈 값과 공백 값 거부
- timezone-aware 입차 시각 계약

`test_main.py`는 `RPi.GPIO`를 module stub으로 대체하고 실제 센서, 카메라,
OCR model과 HTTP 요청을 mock으로 교체한다. PC 테스트 환경은 앞의 설치
준비에서 설명한 플랫폼별 의존성 조건을 따른다.

`test_main.py`는 다음 항목을 검증한다.

- Backend 설정 검증과 startup 오류 경계
- `EntryEvent` 생성과 별도 UUID 두 개 생성
- `+09:00` 입차 시각
- OCR pipeline의 startup 1회 구성과 OCR 설정 전달
- OCR 결과에 따른 Backend 호출 여부
- Backend 요청 필드, OCR `rec_score`의 `ocrConfidence` 매핑과 idempotency key 전달
- OCR 성공 결과의 번호판 또는 대표 `rec_score` 누락에 대한 계약 위반 처리
- `BackendClientError` 처리
- 요청과 응답의 `entryAttemptId` 일치 검증
- `ALLOW`, `REVIEW`, `DENY` 판정별 로그
- BackendClient와 OCR pipeline 재사용
- 예상하지 못한 예외 전파
- 기존 카메라와 센서 cleanup 회귀

센서, 카메라와 OCR pipeline 등 각 컴포넌트의 세부 동작은 해당 테스트
모듈에서 검증한다. 실물 센서, CSI 카메라, 실제 OCR 모델과 Backend를
함께 사용하는 통합 검증은 Raspberry Pi 환경에서 별도로 수행해야 한다.

# Raspberry Pi Entry Service

주차장 입구의 차량 감지, 번호판 촬영 및 OCR을 담당한다.

## 실행 환경

- Python 3.13.5
- Debian GNU/Linux 13 (trixie)

## 목표 처리 흐름

1. 프로그램 실행
2. OCR 모델과 pipeline 1회 로드
3. 초음파 센서로 차량 입차 감지
4. Raspberry Pi에서 입차 이벤트의 `trackingId` 생성
5. `EntryCamera`로 번호판 6프레임 촬영
6. 촬영 프레임에서 번호판 OCR 수행
7. OCR 결과를 Backend 서버로 전송
8. 서버로부터 입차 허용 여부 수신
9. LED로 입차 가능 여부 표시
10. 입차가 허용된 경우 OCR 결과와 `trackingId`를 Jetson으로 전송
11. 다음 차량 입차 감지 대기

## 현재 구현 범위

현재 `src.main`에는 초음파 센서 기반 차량 감지, 6프레임 촬영, OCR
pipeline 실행과 결과 로그 처리가 연결되어 있다.

`trackingId` 생성, Backend 요청, 입차 허용 여부에 따른 LED 제어와
Jetson 전송은 아직 `src.main` 실행 흐름에 연결되어 있지 않다.

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

하드웨어 초기화 이후 서비스가 종료되면 카메라를 먼저 정리하고 센서를
정리한다. 카메라 cleanup 실패는 센서 cleanup을 막지 않으며 cleanup 중
발생한 `KeyboardInterrupt`와 `SystemExit`도 보존한다.

## 테스트

전체 단위 테스트를 실행한다.

```bash
python -m pytest
```

OCR이 연결된 `src.main`의 orchestration 흐름만 확인하려면 다음과 같이
실행한다.

```bash
python -m pytest tests/test_main.py
```

`test_main.py`는 `RPi.GPIO`를 module stub으로 대체하고 센서, 카메라,
OCR factory와 pipeline을 mock으로 교체한다. PC 테스트 환경은 앞의
설치 준비에서 설명한 플랫폼별 의존성 조건을 따른다.

`test_main.py`는 다음 항목을 검증한다.

- OCR pipeline의 startup 1회 구성
- OCR 설정과 6프레임 policy 전달
- 센서와 카메라보다 앞선 OCR factory 호출
- 입차 이벤트 발생 시 촬영과 OCR 실행
- 촬영 frames의 동일 객체 전달
- 여러 입차 이벤트에서 같은 pipeline 재사용
- OCR 결과와 알려진 오류 처리
- 예상하지 못한 예외 전파
- 카메라와 센서 cleanup 순서 및 오류 경계

센서, 카메라와 OCR pipeline 등 각 컴포넌트의 세부 동작은 해당 테스트
모듈에서 검증한다. 실물 센서와 CSI 카메라, 다운로드한 실제 모델을 함께
사용하는 통합 검증은 Raspberry Pi 환경에서 별도로 수행해야 한다.

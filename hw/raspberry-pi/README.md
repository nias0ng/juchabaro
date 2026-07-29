# Raspberry Pi Entry Service

주차장 입구의 차량 감지, 번호판 촬영 및 OCR을 담당한다.

## 실행 환경

- Python 3.13.5
- Debian GNU/Linux 13 (trixie)

## 처리 흐름

1. 프로그램 실행
2. OCR 모델 1회 로드
3. 초음파 센서 감지 대기
4. 차량 감지 시 카메라 촬영
5. 번호판 OCR 수행
6. OCR 결과를 Jetson으로 전송
7. 다시 센서 감지 대기

## 실행

`raspberry-pi` 폴더에서 실행한다.

```bash
python -m src.main
```

## 모델 다운로드

서비스를 처음 실행하기 전에 번호판 탐지 모델과 한국어 PaddleOCR 모델을
다운로드한다. 기본 설치 경로는 `/home/e202/models`이다.

```bash
python scripts/download_models.py
```

다른 경로에 설치하려면 `--models-dir`를 지정한다.

```bash
python scripts/download_models.py --models-dir ./models
```

스크립트는 다음 모델을 설치하고 SHA-256을 검증한다.

- `plate_detector/bestv1_1.pt`: Hugging Face 공개 저장소의 고정 커밋
- `plate_recognizer/`: `korean_PP-OCRv5_mobile_rec` inference 모델

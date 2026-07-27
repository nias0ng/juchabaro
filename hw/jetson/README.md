# Jetson Control Service

주차장 내부 영상 분석, 현장 장치 제어 및 Backend 통신을 담당한다.

## 실행 환경

- Python 3.10.12
- JetPack 6.2.1
- Ubuntu 22.04.5
- FastAPI

## 주요 기능

- Raspberry Pi의 번호판 OCR 결과 수신
- 차량 탐지 및 추적
- 번호판과 Tracking ID 매핑
- 주차 완료 및 주차 상태 판단
- 주차 사건 생성
- 제한 구역 센서 처리
- LED와 스피커 제어
- Backend API 호출
- Backend의 이동 여부 확인 요청 수신

## 가상환경 생성

```bash
python -m venv .venv
```

## 가상환경 활성화

### Windows Git Bash

```bash
source .venv/Scripts/activate
```

### Linux 및 Jetson

```bash
source .venv/bin/activate
```

## 패키지 설치

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 실행 환경에 맞는 값을 설정한다.

## 실행

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

## 상태 확인

```text
GET http://localhost:8000/health
```

## Swagger

```text
http://localhost:8000/docs
```
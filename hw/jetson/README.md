# Jetson Control Service

주차장 내부 영상 분석, 현장 장치 제어 및 Backend 통신을 담당한다.

## 구현 전 필수 참조

`hw/jetson`의 도메인 모델, 상태 전이, 저장 구조 또는 식별자 관련 코드를 수정하기 전에 다음 문서를 확인한다.

- [Jetson 도메인 설계](../../docs/architecture/jetson/README.md)
- [식별자 수명 및 매핑 계약](../../docs/architecture/identifier-contract.md)

위 문서는 목표 계약을 설명하는 Draft이며 현재 구현 상태를 나타내는 inventory가 아니다. 코드와 문서가 충돌하면 임의로 한쪽에 맞추지 말고 차이를 먼저 확인한다. 후속 계약으로 남겨진 API·DTO·wire mapping은 추정해서 구현하지 않는다.

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

아래 명령은 모두 `hw/jetson` 디렉터리에서 실행한다.

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
python -m pip install -r requirements.txt
```

## 테스트 실행

### 개발 의존성 설치

```bash
pip install -r requirements-dev.txt
```

### 실행

```bash
python -m pytest
```

`pyproject.toml`이 `pythonpath`를 잡아주므로 레포 루트에서 실행해도 된다.

```bash
python -m pytest hw/jetson/tests
```

## 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 실행 환경에 맞는 값을 설정한다.

`ZONE_DEFINITION_PATH`에는 현재 카메라 calibration 좌표계에 맞는 versioned
구역 JSON 경로를 지정한다. 개발용 예시는
`config/zone_definition.pilot.json`이다. 구역 정보는 SQLite가 아니라 이 정적
JSON을 원본으로 사용하며, 파일 전체가 유효하지 않으면 기동을 거부한다.

`DATABASE_PATH`는 입차 접수·session correlation·사건 전이를 보존하는
Jetson local SQLite 파일이다. 각 API 요청과 tracking worker는 connection을
공유하지 않고 각자 열어 사용한다. 현재 storage 기반은
aggregate와 immutable outbox row를 같은 SQLite transaction에 저장할 수 있게
한다. `ParkingPipelineResult`를 실제 transaction consumer에 연결하고
outbox publisher를 기동하는 application wiring은 후속 리팩터링 범위다.
Backend endpoint·DTO·Idempotency-Key 형식은 후속 연동 계약이 확정한다.

`EVIDENCE_SPOOL_PATH`는 Incident 정지 이미지 binary를 두는 제한된
file spool 기반이다. 파일당 2MiB, Incident당 2장·4MiB를 넘지 않으며,
`EVIDENCE_SPOOL_CAP_BYTES`는 8GiB를 넘게 설정할 수 없다. root filesystem
여유공간이 35% 보다 작아질 write는 새 capture를 중지하고 30%
보호선을 침범하지 않는다. spool 복구·보존·압박 정리 로직을
제공하지만 capture·upload·기동 흐름에 배선하는 것은 후속 application
리팩터링 범위다. 원본 video는 이 spool의 보존 대상이 아니다.

`ABSENCE_CONFIRMATION_SECONDS`는
ByteTrack timeout이 아니라 정상 전체 구역 관측에서 PhysicalVehicle 미관측을
`NOT_PRESENT_CONFIRMED`로 올리는 별도 시간 기준이다.
`TRUSTED_SAMPLE_MAX_GAP_SECONDS`를 넘는 frame 공백은 camera·pipeline
stall로 보고 그 wall-clock을 부재 확정에 더하지 않는다.

## PC 개발 환경에서 실행

PC에서 동작을 확인할 때는 로컬 인터페이스에 바인딩하고 코드 변경을 자동으로 반영하도록 `--reload`를 사용한다.

```bash
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

## Jetson에서 실행

현재 절차는 Jetson에서 FastAPI 기본 서버를 수동으로 실행하고 동작을 확인하기 위한 것이다.

실제 Jetson에서는 다음 명령으로 모든 네트워크 인터페이스에서 요청을 받는다.

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Jetson에서는 개발용 자동 재시작 기능인 `--reload`를 사용하지 않는다.

`0.0.0.0`은 브라우저에서 접속하는 주소가 아니라 서버가 모든 네트워크 인터페이스의 요청을 받도록 하는 바인딩 주소다.

## 상태 및 API 문서 확인

Jetson 내부에서는 다음 주소로 확인한다.

```text
http://localhost:8000/health
http://localhost:8000/docs
```

같은 네트워크의 다른 PC에서는 `localhost`가 아닌 Jetson의 실제 IP 주소를 사용한다.

```text
http://<JETSON_IP>:8000/health
http://<JETSON_IP>:8000/docs
```

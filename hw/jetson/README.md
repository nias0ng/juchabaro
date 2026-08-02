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
공유하지 않고 각자 열어 사용한다. `FrameObservationWorkflow`는
tracking·session·parking aggregate·physical departure·immutable outbox row를
같은 SQLite transaction에 저장한다. `MonitoringPipeline`은 commit된
PhysicalVehicle 종료만 tracking에 ACK한다. correlation 전에 확정된
PARKED·Incident는 pending marker로 보존하고, 늦은 authoritative
correlation이 오면 원래 occurredAt·revision 순서로 outbox를 만든다.
`build_monitoring_pipeline()`은 이 owner들을 하나의 frame Unit of Work로
조립하지만, 임시 Backend serializer나 장치 설정을 발명하지 않고
배포 계층에서 명시적으로 주입받는다.

재시작은 active observation을 `UNKNOWN / PROCESS_RESTARTED`로 끊고
downtime을 trusted timer에 더하지 않는다. 현재 기본
`PassthroughEntityResolver`는 process 간 재식별을 지원하지 않으므로,
복원한 차량이 있는데 detection이 남아 있으면 신규 scope 생성과
부재 확정을 멈춘다. 정상 전체 영역이 빈 관측에서만
보수적 종료를 재개한다. process 간 재식별 adapter는
`RestartAwareEntityResolver`를 구현해 복구 후보를 인계받을 수 있지만,
실제 재식별 근거와 구현은 후속 범위다.

`main.py`는 migration, ZoneDefinition 검증, inbound application 조립과
단일 monitoring thread의 시작·정상 종료 생명주기를 소유한다.
Backend endpoint·DTO·Idempotency-Key를 exact bytes로 만드는 adapter와
outbox publisher는 후속 연동 계약 범위이다. 따라서 module-level
FastAPI `app`은 아직 API-only이며, 그 계약을 구현한 배포 entrypoint가
`MonitoringPipelineFactory`를 명시적으로 주입했을 때만 camera·model owner를
하나 기동한다. 계약 확정 전 임시 serializer나 no-op publisher는
사용하지 않는다.

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

Camera·보정 실패는 `FrameSourceError`의 `UNKNOWN` 또는 `DEGRADED`
관측과 구체적인 reason으로 변환된다. `MonitoringPipeline`은 이 비신뢰
관측을 active scope에 commit해 timer chain을 끊은 뒤 원래 오류를
호출자에게 전달한다. LED·speaker는 concrete GPIO 구현 없이
`ActuatorCommandPlanner`와 `ActuatorPort` 주입 경계만 제공하며, durable
commit 뒤 전체 active Incident projection을 반복 적용한다. `src/sensors`는
후속 센서 입력 adapter를 위한 독립 경계이며 현재 실행 pipeline에는 연결하지 않는다.

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

## 파일럿 영상 리플레이

§4.7 임계값(`zone_entry_confirm_seconds`, `movement_epsilon`)을 산출하거나
회귀를 확인할 때는 녹화된 파일럿 영상을 새 파이프라인에 그대로 흘려보낼 수
있다.

```bash
python -m scripts.replay_pilot_video \
    --video ../../docs/video/video1.mp4 \
    --zones-file ../../ai/tracking/zones_pilot.json \
    --calibration ../../ai/tracking/camera_calibration.json \
    --model-path ../../ai/training/yolo26n.pt \
    --zone-entry-confirm-seconds 3.0 --zone-exit-confirm-seconds 3.0 \
    --movement-epsilon 0.01 \
    --out-events out/video1_events.jsonl \
    --out-zone-visits out/video1_zone_visits.jsonl
```

`--out-events`는 확정된 사건 전이(프로덕션 outbox와 같은 포맷)만 담는다.
파일럿 영상 리플레이에는 백엔드 입차 이벤트가 없어 `restricted_zone` 규칙이
항상 미확정(`confirmable=False`)으로 남으므로, 임계값 측정에는
`--out-zone-visits`(ZoneVisit의 ENTERING→INSIDE 전이 로그)를 쓴다. 각 레코드의
`observedAt`은 상태별로 의미가 맞는 시각(ENTERING은 진입 후보 시각, INSIDE는
진입 확정 시각, EXITING은 이탈 후보 시각, OUTSIDE는 이탈 확정 시각)을 골라
담은 필드라, 상태를 가리지 않고 이 필드 하나로 정렬·비교할 수 있다.

`ai/tracking/replay_pilot_video.py`는 옛 baseline(`jetson_vehicle_tracking_baseline.py`)
전용이며 이 스크립트가 대체하지 않는다 — 그쪽의 폐기는 별도 티켓(T-23) 범위다.

**실제 실행은 재현되지 않는다.** 위 예시나 실제 파일럿 영상 실행은
`zoneVisitId`/`physicalVehicleId`를 매번 새 난수(`uuid4()`)로 발급하므로, 같은
영상을 두 번 돌려도 두 필드는 실행마다 달라진다. 회귀 확인차 두 실행의
`--out-zone-visits`를 diff한다면 그 두 필드는 제외하고 `zoneId`/`state`/
`observedAt`만 비교한다.

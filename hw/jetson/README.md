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

기존 `.env`를 계속 사용하는 환경은 `.env.example`과 비교해 카메라·
calibration·차량 tracking 및 MonitoringPolicy 필수값을 추가해야 한다.
기본값 없는 항목은 누락하거나 빈 값으로 두면 시작 단계에서 설정 오류로
중단한다. provisional 값은 각 주석의 출처와 재측정 조건을 확인한 뒤
배포 환경에 맞게 명시한다.

`ZONE_DEFINITION_PATH`에는 현재 카메라 calibration 좌표계에 맞는 versioned
구역 JSON 경로를 지정한다. 기본 운영 정본은
`config/zone_definition.json` version 1이다. 이 파일은 crop하지 않은
full-frame 좌표계를 사용한다. 구역 정보는 SQLite가 아니라 이 정적 JSON을
원본으로 사용하며, 파일 전체가 유효하지 않으면 기동을 거부한다.

`config/zone_definition.pilot.json` version 6은 좌측 150px crop을 적용하는
`replay_pilot_video.py`와 `watch_live_stream.py`용 설정이다. 메인 배포와
Pipeline Viewer의 full-frame 입력에는 사용하지 않는다.

`DATABASE_PATH`는 입차 접수·session correlation·사건 전이를 보존하는
Jetson local SQLite 파일이다. 각 API 요청과 tracking worker는 connection을
공유하지 않고 각자 열어 사용한다. `FrameObservationWorkflow`는
tracking·session·parking aggregate·physical departure·immutable outbox row를
같은 SQLite transaction에 저장한다. `MonitoringPipeline`은 commit된
PhysicalVehicle 종료만 tracking에 ACK한다. correlation 전에 확정된
PARKED·Incident는 pending marker로 보존하고, 늦은 authoritative
correlation이 오면 원래 occurredAt·revision 순서로 outbox를 만든다.
`build_monitoring_pipeline()`은 이 owner들을 하나의 frame Unit of Work로
조립하고, `RuntimeContext`가 제공하는 `BackendPublicationPreparer`를 배포
계층에서 명시적으로 주입받는다. 이 adapter는 API 6(PARKED·UNPARKED),
API 7(Incident OPEN·RESOLVE), API 10(SessionExit)의 exact JSON과
Idempotency-Key를 outbox 저장 전에 한 번만 확정한다. Incident 전송 시
`EV_ZONE_UNAUTHORIZED`와 `AISLE_BLOCK`은 현재 Backend enum 계약에 맞춰
wire `ruleCode=ETC`로 축약하되 local Incident의 ruleCode는 바꾸지 않는다.

`src.main:app`은 운영 `MonitoringPipelineFactory`를 명시적으로 주입해
camera·model owner를 하나만 기동한다. 테스트나 API-only 실행에서
`create_app()`을 직접 호출할 때는 factory를 생략할 수 있다.

재시작은 active observation을 `UNKNOWN / PROCESS_RESTARTED`로 끊고
downtime을 trusted timer에 더하지 않는다. 현재 기본
`PassthroughEntityResolver`는 process 간 재식별을 지원하지 않으므로,
복원한 차량이 있는데 detection이 남아 있으면 신규 scope 생성과
부재 확정을 멈춘다. 정상 전체 영역이 빈 관측에서만
보수적 종료를 재개한다. process 간 재식별 adapter는
`RestartAwareEntityResolver`를 구현해 복구 후보를 인계받을 수 있지만,
실제 재식별 근거와 구현은 후속 범위다.

`main.py`는 migration, ZoneDefinition 검증, inbound application 조립,
outbox publisher, evidence publication worker와 단일 monitoring thread의 시작·정상 종료 생명주기를
소유한다. 종료 시 monitoring·MoveVerification producer를 먼저 멈춘 뒤 publication
worker를 회수한다. 진행 중 작업은 완료까지 기다리지만 queue 전체를 drain하지
않으며, 남은 durable 작업은 다음 기동의 recovery에서 이어간다.
`BACKEND_HW_API_KEY`가 비어 있으면 outbound publisher를 기동하지 않으며,
값이 있으면 `BACKEND_BASE_URL`로 전송하는 두 worker를 기동한다. outbox publisher는
API 6·7·10·12의 exact JSON bytes를, evidence publication worker는 API 8·9를
담당한다. 네트워크·5xx는 지수 backoff로 재시도하고 4xx·ACK 계약 위반·payload
충돌은 `FAILED_TERMINAL`로 격리한다. outbox의 `APPLIED`와 `ALREADY_APPLIED` ACK는
payload hash까지 검증한 뒤 14일 delivery receipt로 보존한다. evidence ACK와
전송 상태는 해당 artifact metadata에 보존한다.

## Backend → Jetson 내부 API 계약

Jetson은 `0.0.0.0:8000`에 수신 서버를 열며 실제 Backend base URL은 EC2에서
접근 가능한 Jetson IP·DNS·터널 주소로 정한다. `/home/e202` 같은 배포 경로는
네트워크 주소가 아니다.

```text
POST /internal/entry-review-resolutions
POST /internal/session-context-updates
POST /internal/move-verifications
```

모든 요청은 `X-Internal-API-Key`와 `Idempotency-Key`를 포함한다. API key는
local `.env`의 `INTERNAL_API_KEY`에만 저장하고 Git에는 넣지 않는다.
`Idempotency-Key`는 command identity·revision·payload와 함께 SQLite에 기간
제한 없이 보존한다. 같은 key와 같은 payload는 재적용하지 않으며, 같은 key나
identity·revision을 다른 payload에 사용하면 `409 IDEMPOTENCY_CONFLICT`다.
이미 더 높은 revision이 반영된 뒤 처음 도착한 낮은 revision은 상태를 바꾸지
않고 `202 STALE`로 확인한다. `MoveVerification`은 수신 시점이 `deadlineAt`을
지난 경우에도 실행 scope를 만들지 않고 같은 결과를 반환한다.

성공은 Backend `ApiResponse<HwPublicationAck>`와 대칭인 JSON을 반환한다.
여기서 `APPLIED`는 API 11의 현장 재확인 완료가 아니라 command가 Jetson의
durable workflow에 반영됐다는 의미다.

접수된 command는 별도 실행 worker가 `ACCEPTED → CHECKING → COMPLETED`로
처리한다. API 11 접수 이후의 최신 Incident가 `OPEN`이고 관측이 정상이라면
`STILL_ACTIVE`, 모든 대상이 `RESOLVED`라면 `RESOLVED`다. `CLEAR_PENDING`,
관측 불가, 접수 전의 오래된 관측은 `deadlineAt`까지 다시 확인하고 끝까지
확정되지 않으면 `UNKNOWN`으로 완료한다.
완료 상태와 아래 API 12 outbox 레코드는 한 SQLite transaction에 저장한다.

```text
POST /api/hw/move-requests/{requestId}/verification
Idempotency-Key: MoveVerificationAttempt:{requestId}:{verificationAttempt}:{publicationRevision}
```

process가 중단돼도 `CHECKING` command를 다음 기동에서 다시 읽으며, API 12의
네트워크·5xx 실패는 기존 outbox backoff 정책으로 같은 key와 payload를 재전송한다.

```json
{
  "httpStatus": "ACCEPTED",
  "isSuccess": true,
  "message": "명령이 durable하게 접수되었습니다.",
  "code": 202,
  "result": {
    "aggregateType": "MoveVerification",
    "aggregateId": "201",
    "publicationRevision": 1,
    "applicationResult": "APPLIED",
    "backendCorrelation": {
      "acceptedAt": "2026-08-04T06:00:00+00:00"
    }
  }
}
```

`applicationResult`는 `APPLIED`, `ALREADY_APPLIED`, `STALE` 중 하나다. 실패는
같은 `ApiResponse` envelope의 `result.errorType`과 `retryable`로 분류한다.
네트워크 오류·timeout·`retryable=true`만 동일 key와 payload로 재시도하고
나머지 4xx는 재시도하지 않는다.

camera·model owner는 배포 entrypoint가 `MonitoringPipelineFactory`를
명시적으로 주입했을 때만 하나 기동한다. Monitoring recovery가 끝난 뒤
outbox publisher를 시작하므로 복구 중인 aggregate와 동시에 전송하지 않는다.

`EVIDENCE_SPOOL_PATH`는 Incident 정지 이미지 binary를 두는 제한된
file spool 기반이다. 파일당 2MiB, Incident당 2장·4MiB를 넘지 않으며,
`EVIDENCE_SPOOL_CAP_BYTES`는 8GiB를 넘게 설정할 수 없다. root filesystem
여유공간이 35% 보다 작아질 write는 새 capture를 중지하고 30%
보호선을 침범하지 않는다. 원본 video는 이 spool의 보존 대상이 아니다.

Evidence publication worker는 기동 시 spool과 중단된 전송을 복구한다.
전송 가능한 `READY` binary는 API 8로 업로드하고, 보존 만료·저장공간 압박·손상
등으로 binary를 제공할 수 없는 `FAILED`·`EVICTED` artifact는 API 9로 알린다.
각 요청의 멱등 키는 아래 형식이며 재시도할 때 같은 key와 exact payload를 유지한다.

```text
EvidenceArtifact:{evidenceId}:{publicationRevision}
EvidenceUnavailable:{evidenceId}:{publicationRevision}
```

네트워크·timeout·5xx는 1초부터 최대 300초까지 지수 backoff로 계속 재시도한다.
4xx와 ACK 계약 위반은 `FAILED_TERMINAL`로 격리하며 자동 재시도하지 않는다.
전송 시도·다음 재시도 시각·Backend ACK는 SQLite에 보존하므로 process가
중단돼도 동일 publication identity로 이어서 처리한다. API 8 직전에 파일 손실이나
checksum 불일치를 발견하면 해당 binary를 `LOST_OR_CORRUPTED`로 확정하고 API 9로
전환한다. `MonitoringPipeline`은 frame transaction commit 후 생성된
`evidence_capture_intents`를 `EvidenceCaptureCoordinator`에 전달해 JPEG spool과
SQLite metadata를 기록한다.

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

`src.main:app`은 FastAPI와 함께 camera·tracking MonitoringWorker를 시작한다.
따라서 `.env`의 camera·calibration·model 및 MonitoringPolicy 설정이 유효해야
하며, asset preflight 또는 장치 open이 실패하면 서버 startup도 실패한다.
PC 개발 환경에서도 접근 가능한 camera와 calibration/model asset이 필요하다.

PC에서 동작을 확인할 때는 로컬 인터페이스에 바인딩하고 코드 변경을 자동으로 반영하도록 `--reload`를 사용한다.

```bash
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

## Jetson ToF 센서 실행 전 GPIO pinmux 설정

VL53L0X 두 센서의 XSHUT은 물리 Pin 15와 Pin 29에 연결한다. 어댑터는
XSHUT을 push-pull LOW/HIGH 출력 방식으로 제어하지만 Jetson의 기본 pinmux
상태에서는 두 핀이 GPIO 출력으로 준비되지 않을 수 있다. 애플리케이션에서
PADCTL을 직접 변경하지 않으므로 Jetson 재부팅 후 최초 ToF 실행 전에 운영자가
한 번 설정해야 한다.

### 검증 환경과 배선

아래 절차는 다음 환경에서 실물 검증한 보드 전용 임시 설정이다.

```text
Jetson Orin Nano Engineering Reference Developer Kit Super
Module: P3767-0005
Carrier: P3768-0000
Jetson Linux: R36.4.7
JetPack: 6.2.1
```

XSHUT 배선은 다음과 같다.

```text
물리 Pin 15: 장애인 구역 센서 XSHUT
물리 Pin 29: 전기차 구역 센서 XSHUT
```

검증한 SoC 핀과 PADCTL 정보는 다음과 같다.

```text
Pin 15: PN.01 / GP88_PWM1 / PADCTL 0x2440020 / 출력 설정값 0x5
Pin 29: PQ.05 / GP65 / PADCTL 0x2430068 / 출력 설정값 0x8
```

### BusyBox 확인

`devmem` 실행에 사용할 BusyBox가 설치되어 있는지 확인한다.

```bash
command -v busybox
```

설치되어 있지 않다면 다음 명령으로 설치해야 한다.

```bash
sudo apt install busybox
```

### 재부팅 후 pinmux 설정

Jetson을 재부팅한 뒤 ToF 어댑터나 진단 스크립트를 처음 실행하기 전에 다음
명령을 한 번 수행한다.

```bash
sudo busybox devmem 0x2440020 w 0x5
sudo busybox devmem 0x2430068 w 0x8
```

이 설정은 같은 부팅 세션에서 스크립트를 실행할 때마다 반복할 필요가 없다.
재부팅하면 사라지므로 다음 부팅 세션의 최초 ToF 실행 전에 다시 적용한다.

### 적용값 확인

다음 명령으로 현재 PADCTL 값을 확인한다.

```bash
sudo busybox devmem 0x2440020
sudo busybox devmem 0x2430068
```

명령 순서대로 예상되는 값은 다음과 같다.

```text
0x00000005
0x00000008
```

### ToF 진단 실행

다음은 실물 진단에 사용한 별도 가상환경을 활성화하고 센서를 세 번 측정하는
예시다. `.venv-tof`는 이 진단 환경의 이름이며 프로젝트 공통 가상환경 이름은
아니다.

```bash
source .venv-tof/bin/activate
python -m scripts.check_vl53l0x --count 3 --interval-seconds 0.5
```

### 제한 및 주의 사항

- 위 PADCTL 주소와 값은 명시한 Orin Nano Developer Kit Super 및 Jetson Linux
  R36.4.7 환경에서 실물 검증한 값이다.
- 다른 Jetson 모델, 캐리어 보드 또는 Jetson Linux 버전에 그대로 적용하지
  않는다.
- JetPack 또는 Jetson Linux 업데이트 후에는 PADCTL 주소와 설정값을 다시
  확인해야 한다.
- Jetson-IO에서 `pwm1 (15)` 또는 `extperiph3_clk (29)`를 선택하면 GPIO가
  아니라 특수 기능으로 설정된다.
- 애플리케이션과 `check_vl53l0x.py`는 `sudo` 또는 `devmem`을 자동으로
  실행하지 않는다.
- 운영 자동화가 필요하면 후속 배포 작업에서 systemd 사전 서비스 또는 정식
  MB1 pinmux 설정으로 분리한다.
- XSHUT에 5V를 직접 연결하지 않는다.

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

§4.7 임계값과 MotionEstimator의 시간 창·정규화 evidence 기준을 산출하거나
회귀를 확인할 때는 녹화된 파일럿 영상을 새 파이프라인에 그대로 흘려보낼 수
있다.

```bash
python -m scripts.replay_pilot_video \
    --video ../../docs/video/video1.mp4 \
    --zones-file config/zone_definition.pilot.json \
    --calibration ../../ai/tracking/camera_calibration.json \
    --model-path ../../ai/training/yolo26n.pt \
    --zone-entry-confirm-seconds 3.0 --zone-exit-confirm-seconds 3.0 \
    --parking-confirm-seconds 5.0 --parking-move-confirm-seconds 0.5 \
    --absence-confirmation-seconds 5.0 \
    --trusted-sample-max-gap-seconds 1.0 \
    --motion-window-seconds 0.75 \
    --motion-min-observation-span-seconds 0.20 \
    --motion-max-sample-gap-seconds 0.50 \
    --motion-stationary-threshold 0.03 \
    --motion-moving-threshold 0.10 \
    --motion-min-samples 3 \
    --motion-min-trend-consistency 0.60 \
    --reidentification-max-gap-seconds 4.0 \
    --reidentification-min-score 0.42 \
    --reidentification-ambiguity-margin 0.08 \
    --assignment-min-overlap-ratio 0.5 --assignment-ambiguous-margin 0.05 \
    --bad-parking-min-primary-overlap-ratio 0.75 \
    --bad-parking-min-secondary-overlap-ratio 0.25 \
    --out-of-zone-min-spot-overlap-ratio 0.50 \
    --blocking-relation-confirm-seconds 1.0 \
    --blocking-relation-clear-seconds 1.0 \
    --out-events out/video1_events.jsonl \
    --out-zone-visits out/video1_zone_visits.jsonl
```

임계값 플래그에 임의 기본값을 두지 않는 것은 `config/settings.py`와 같은
이유다(§4.7) — 이 스크립트가 그 실측 도구라 숨은 숫자가 있으면 측정값 자체가
오염된다. 코드에 이미 확립된 기본값이 있는 값(`--entry-zone-min-overlap-ratio`,
`--incident-confirm-seconds`, `--incident-clear-seconds`,
`--parking-confirm-seconds`)만 그 값을 재사용한다.

위 PARKED 5.0초와 movement 0.5초는 Pipeline Viewer 판정 테스트의 명시적
override다. 일반 배포의 PARKED 600초 기본 정책을 변경하지 않는다. 재식별
세 값도 아직 파일럿 export로 조정해야 하는 `[제안값]`이다.
MotionEstimator의 일곱 값도 bbox 크기로 정규화한 provisional 기준이며,
Pipeline Viewer diagnostic export의 signal·reason·지표 분포로 재조정한다.
`parking-move-confirm-seconds`는 ParkingEpisode timer이고
`motion-max-sample-gap-seconds`는 motion history 연속성 기준이므로 서로
대체할 수 없다.

`--zones-file`은 464의 새 구역 정의 snapshot 포맷이어야 한다
(`zoneDefinitionVersion`/`calibrationReference`/`zones`). `calibrationReference`가
`--calibration` 파일의 지문과 다르면 실행 전에 거부한다 — 런타임에서 그
문자열이 프레임의 `calibration_id`와 비교되어 전체 관측 여부를 가르므로,
어긋난 채 돌리면 모든 프레임이 조용히 부분 관측으로 격하된다.

`--out-events`는 확정된 사건 전이(프로덕션 outbox와 같은 포맷)만 담는다.
파일럿 영상 리플레이에는 백엔드 입차 이벤트가 없어 `ParkingSession`이 하나도
없고, 세 종류 전이(PARKED/UNPARKED, 사건 OPEN/RESOLVE, 세션 EXIT)가 모두
session correlation을 요구하므로 이 파일은 비어 있다. 따라서 임계값 측정에는
`--out-zone-visits`(ZoneVisit의 ENTERING→INSIDE 전이 로그)를 쓴다. 각 레코드의
`observedAt`은 상태별로 의미가 맞는 시각(ENTERING은 진입 후보 시각, INSIDE는
진입 확정 시각, EXITING은 이탈 후보 시각, ENDED/CANCELED는 종료 시각)을 골라
담은 필드라, 상태를 가리지 않고 이 필드 하나로 정렬·비교할 수 있다.

`ai/tracking/replay_pilot_video.py`는 옛 baseline(`jetson_vehicle_tracking_baseline.py`)
전용이며 이 스크립트가 대체하지 않는다 — 그쪽의 폐기는 별도 티켓(T-23) 범위다.

**실제 실행은 재현되지 않는다.** 위 예시나 실제 파일럿 영상 실행은
`zoneVisitId`/`physicalVehicleId`를 매번 새 난수(`uuid4()`)로 발급하므로, 같은
영상을 두 번 돌려도 두 필드는 실행마다 달라진다. 회귀 확인차 두 실행의
`--out-zone-visits`를 diff한다면 그 두 필드는 제외하고 `zoneId`/`state`/
`observedAt`만 비교한다.

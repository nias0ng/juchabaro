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
- Jetson Linux R36.4.7
- TensorRT 10.3.0
- VPI 3.2.4
- PyTorch 2.8.0 (CUDA 12.6 build)
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

`requirements.txt`는 애플리케이션의 pip 의존성만 복원한다. CUDA, TensorRT,
VPI는 JetPack 시스템 runtime이며 pip requirements로 대체하지 않는다. 현장에서
검증한 시스템 패키지는 다음과 같이 확인한다.

```bash
head -n 1 /etc/nv_tegra_release
dpkg-query -W \
  tensorrt \
  python3-libnvinfer \
  libnvvpi3 \
  python3.10-vpi3
```

패키지가 없다면 NVIDIA JetPack apt repository가 설정된 상태에서 설치한다.

```bash
sudo apt update
sudo apt install -y \
  tensorrt \
  python3-libnvinfer \
  libnvvpi3 \
  python3.10-vpi3
```

`REMAP_BACKEND=vpi`는 PyPI 패키지가 아니라 JetPack의
`python3.10-vpi3` binding을 사용한다. 시스템 Python에서는 VPI가 보이지만
격리된 venv에서는 보이지 않으므로, Jetson에서 binding 파일 하나만 venv에
연결한다. `--system-site-packages`는 시스템 OpenCV까지 섞을 수 있어 사용하지
않는다.

```bash
VPI_BINDING_PATH=$(/usr/bin/python3 -c 'import vpi; print(vpi.__file__)')
VENV_SITE_PACKAGES=$(python -c 'import site; print(site.getsitepackages()[0])')
ln -sf "$VPI_BINDING_PATH" "$VENV_SITE_PACKAGES/"
python -c 'import vpi; print(vpi.__file__, vpi.Backend.CUDA)'
```

TensorRT Python binding도 JetPack 시스템 패키지를 사용한다. 시스템 Python이
로드한 TensorRT site directory만 venv에 추가하고, pip OpenCV·NumPy·PyTorch는
venv의 버전을 유지한다.

```bash
TENSORRT_SYSTEM_SITE=$(
  /usr/bin/python3 -c \
    'from pathlib import Path; import tensorrt; print(Path(tensorrt.__file__).resolve().parent.parent)'
)
printf '%s\n' "$TENSORRT_SYSTEM_SITE" \
  > "$VENV_SITE_PACKAGES/jetpack-tensorrt.pth"
```

아래 preflight가 모두 통과해야 현재 현장 runtime과 같은 추론 경로를 사용할 수
있다.

```bash
python - <<'PY'
import cv2
import numpy
import tensorrt
import torch
import vpi

print("TensorRT:", tensorrt.__version__, tensorrt.__file__)
print("VPI:", vpi.__version__, vpi.__file__)
print("torch:", torch.__version__, "CUDA build:", torch.version.cuda)
print("numpy:", numpy.__version__, numpy.__file__)
print("OpenCV:", cv2.__version__, cv2.__file__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("CUDA device:", torch.cuda.get_device_name(0))
PY
```

기존 TensorRT engine을 실행할 때 ONNX는 필요하지 않다. 원본 `.pt`에서 engine을
다시 생성할 때만 현장에서 검증한 `onnx==1.22.0`을 별도로 설치한다.

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
calibration·차량 tracking·`EGRESS_AISLE_PATH` 및 MonitoringPolicy 필수값을
추가해야 한다.
핵심 monitoring의 기본값 없는 항목은 누락하거나 빈 값으로 두면 시작 단계에서
설정 오류로 중단한다. optional ToF runtime의 필수값과 격리 동작은 아래 계약을
따른다. provisional 값은 각 주석의 출처와 재측정 조건을 확인한 뒤 배포 환경에
맞게 명시한다.

### ToF 현장 경고 runtime 활성화

`src.main:app`은 production ToF factory를 연결한다. 환경 변수를 제공하지
않았을 때 `Settings`의 기본값은 `TOF_ENABLED=false`이며, 이 경우 실제
센서·LED·speaker runtime을 구성하지 않는다. 현재 `.env.example`은 현장
시연 배포를 위해 `true`와 provisional 측정값을 명시한다. `true`로
활성화하려면 다음 core 설정을 모두 명시해야 한다.

```text
TOF_I2C_BUS
TOF_SHUTDOWN_SETTLE_SECONDS
TOF_BOOT_SETTLE_SECONDS
TOF_IO_TIMEOUT_SECONDS
TOF_DISABLED_ZONE_ID
TOF_EV_CHARGING_ZONE_ID
TOF_POLL_INTERVAL_SECONDS
TOF_ENTER_DISTANCE_MM
TOF_EXIT_DISTANCE_MM
TOF_ENTER_CONFIRM_SECONDS
TOF_EXIT_CONFIRM_SECONDS
TOF_TRUSTED_SAMPLE_MAX_GAP_SECONDS
TOF_STALE_AFTER_SECONDS
TOF_OCCUPANCY_FRESHNESS_SECONDS
TOF_MONITORING_FRESHNESS_SECONDS
TOF_MAX_PRE_OCCUPANCY_OBSERVATION_SECONDS
```

두 zone ID는 각각 배포된 `DISABLED`, `EV_CHARGING` ZoneDefinition을 가리켜야
한다. `.env.example`의 freshness와 재평가 backoff는 현장 시연용
provisional 값이므로 camera frame 처리율·SQLite 부하·허용 경고 지연을
실측한 뒤 재조정한다. core 설정이
누락됐거나 의미 검증에 실패하면 FastAPI·camera monitoring은 계속 실행하고
ToF runtime만 비활성화하며 application log에 원인을 남긴다.

speaker는 다음 세 값을 모두 제공할 때만 활성화한다. 모두 없으면 speaker만
사용하지 않고, 일부만 있거나 초기화에 실패해도 sensor와 LED는 계속 동작한다.

```text
TOF_DISABLED_ZONE_WARNING_WAV_PATH
TOF_EV_ZONE_WARNING_WAV_PATH
TOF_WARNING_AUDIO_DEVICE
```

장애인·EV 전용구역의 현장 경고는 stable ToF `OCCUPIED`로 시작한 점유 구간만
활성화할 수 있다. 차량·binding·자격·monitoring 갱신은 활성 점유 구간의
재평가 신호이며 독립적인 경고 trigger가 아니다. Incident OPEN·RESOLVE는
LED·speaker를 제어하지 않고 기존 durable 기록·Backend 전파만 담당한다.
자세한 계약은 [Jetson 도메인 설계](../../docs/architecture/jetson/README.md)를
따른다.

단일 USB 카메라를 사용하는 Jetson 운영 배치는 `hw/jetson`을 하나의 배포
단위로 사용한다. 모델 binary를 제외한 calibration·manifest·WAV는 저장소에서
관리하고, Git에서 제외한 `.pt`와 `.engine`은 검증된 배포 bundle에서 복원한다.

```text
hw/jetson/
├─ config/camera_calibration.json
├─ model/yolov8s.pt
├─ model/yolov8s-fp16-384x640.engine
├─ model/yolov8s-fp16-384x640-manifest.json
└─ assets/audio/
   ├─ disabled_zone_warning.wav
   └─ ev_zone_warning.wav
```

상대경로는 현재 working directory를 기준으로 해석되므로 Jetson에서도 반드시
`/home/e202/jetson`으로 이동한 뒤 실행한다.

```dotenv
CAMERA_ID=PARKING-CAMERA-01
CAMERA_INDEX=0
CALIBRATION_PATH=config/camera_calibration.json
REMAP_BALANCE=0.5
VEHICLE_MODEL_PATH=model/yolov8s-fp16-384x640.engine
VEHICLE_MODEL_MANIFEST_PATH=model/yolov8s-fp16-384x640-manifest.json
TOF_DISABLED_ZONE_WARNING_WAV_PATH=assets/audio/disabled_zone_warning.wav
TOF_EV_ZONE_WARNING_WAV_PATH=assets/audio/ev_zone_warning.wav
```

차량 모델 binary와 manifest는 항상 같은 release를 배치한다. 기동
preflight이 manifest의 SHA-256을 binary와 대조하고, model open 후에
Ultralytics `task='detect'`와 `names={0: 'vehicle'}`를 다시 검증한다.
두 검증 중 하나라도 실패하면 camera monitoring은 시작하지 않는다.

시연 배포에서 판정 정책은 `.env` → `Settings` → `src.main`의 composition root →
`MonitoringPolicy` 순서로 전달된다. 규칙별 Incident 값은
`MonitoringPolicy.incident_rule_timings`를 거쳐 `InMemoryIncidentReducer`가 새
Incident에 snapshot하므로, 실행 중 환경 변수가 바뀌어도 이미 진행 중인 timer의
정책은 바뀌지 않는다.

알려진 Incident 규칙은 아래 값을 모두 명시해야 한다. 전역
`INCIDENT_CONFIRM_SECONDS`와 `INCIDENT_CLEAR_SECONDS`는 아직 규칙별 정책이 없는
미래 규칙을 위한 compatibility fallback일 뿐이다.

```dotenv
INCIDENT_DISABLED_ZONE_UNAUTHORIZED_CONFIRM_SECONDS=0.0
INCIDENT_DISABLED_ZONE_UNAUTHORIZED_CLEAR_SECONDS=0.0
INCIDENT_EV_ZONE_UNAUTHORIZED_CONFIRM_SECONDS=0.0
INCIDENT_EV_ZONE_UNAUTHORIZED_CLEAR_SECONDS=0.0
INCIDENT_EV_OVERSTAY_CONFIRM_SECONDS=0.0
INCIDENT_EV_OVERSTAY_CLEAR_SECONDS=0.0
INCIDENT_BAD_PARKING_CONFIRM_SECONDS=0.5
INCIDENT_BAD_PARKING_CLEAR_SECONDS=0.5
INCIDENT_OUT_OF_ZONE_CONFIRM_SECONDS=0.5
INCIDENT_OUT_OF_ZONE_CLEAR_SECONDS=0.5
INCIDENT_AISLE_BLOCK_CONFIRM_SECONDS=0.5
INCIDENT_AISLE_BLOCK_CLEAR_SECONDS=0.5
INCIDENT_DOUBLE_PARKING_CONFIRM_SECONDS=0.0
INCIDENT_DOUBLE_PARKING_CLEAR_SECONDS=0.0
```

`DISABLED_ZONE_UNAUTHORIZED`와 `EV_ZONE_UNAUTHORIZED`는 confirmed ZoneVisit만으로
OPEN하지 않는다. 차량이 같은 전용 주차면에 `PARKED`되고 고정된
`ParkingAssignment.zoneId`가 방문 zone과 일치한 뒤에만 무자격 Incident를
확정한다. `MOVE_PENDING`은 기존 사건을 유지하고, 이동이 확정되면 재평가해
해소한다.

`EV_OVERSTAY`도 같은 EV zone의 `PARKED`를 요구하며, ZoneVisit 진입 시각이
아니라 `ParkingEpisode.parkedAt`부터 wall-clock 경과 시간을 계산한다. Backend는
PARKED 전이 시 같은 시각을 `ParkingSession.parkedAt`으로 저장하고 `dueAt`을
표시하지만 초과 Incident의 생성과 증거 수집은 Jetson이 담당한다.

`DOUBLE_PARKING`의 `BlockingRelation`은 피해 차량과 방해 차량이 모두
`PARKED`일 때만 생성·유지한다. 신뢰 가능한 관측에서 한쪽이 PARKED를 벗어나면
relation clear timer를 시작하며, 통로에 남은 차량 자체의 위반은
`AISLE_BLOCK`이 독립적으로 평가한다.

현재 시연값은 `VEHICLE_TRACKING_CONFIDENCE=0.25`,
`PARKING_CONFIRM_SECONDS=5.0`, `PARKING_MOVE_CONFIRM_SECONDS=0.5`다.
`PARKING_CONFIRM_SECONDS=600.0`은 운영 요구값이며 실영상 검증을 마친 운영
프로파일에서 별도로 적용한다. 이 값들은 provisional이므로 영상별 confidence 분포와
Incident 오탐·미탐을 다시 측정한 뒤 조정한다.

`config/camera_calibration.json`은 운영 배포용 calibration 정본이다. 이 파일의
원시 바이트 SHA-256 앞 16자리는 `a26d3085c3d4fc4f`이며,
`zone_definition.json`과 `egress_aisle.json`의 `calibrationReference`가 같은
값이어야 한다. 해당 reference는 보정 수치로 사용하는 값이 아니라, 보정된
frame과 polygon이 같은 좌표계인지 검증하는 식별자다. 파일을 다시 저장할 때
줄바꿈이나 공백이 달라져도 지문이 바뀌므로 Git의 LF 바이트를 유지한다.

`ZONE_DEFINITION_PATH`에는 현재 카메라 calibration 좌표계에 맞는 versioned
구역 JSON 경로를 지정한다. 기본 운영 정본은
`config/zone_definition.json` version 2다. 이 파일은 crop하지 않은
full-frame 좌표계를 사용한다. 구역 정보는 SQLite가 아니라 이 정적
JSON을 원본으로 사용하며, 파일 전체가 유효하지 않으면 기동을 거부한다.

`config/zone_definition.pilot.json` version 7은 좌측 150px crop을 적용하는
`replay_pilot_video.py`와 `watch_live_stream.py`용 설정이다. 메인 배포와
Pipeline Viewer의 full-frame 입력에는 사용하지 않는다.

EXIT role 구역의 `exitTraversal`은 기준선·외향점·hysteresis를 명시한다.
외향 통과는 SQLite checkpoint로 보존되며
`EXIT_REENTRY_CONFIRMATION_SECONDS` 동안 연속 내향 관측된 경우에만
재진입으로 취소한다. 이 값은 ZoneVisit 진입·이탈 confirmation과 별도다.

`EGRESS_AISLE_PATH`는 이중주차 `BlockingRelation`에만 사용하는
주차면별 출차 방해 영역 JSON 경로다. `ZoneDefinition`의
Viewer overlay·side mask·ZoneVisit·`AISLE_BLOCK`에는 투영하지 않는다.
기동 시 `zoneDefinitionVersion`과 `calibrationReference`가 현재
Zone snapshot과 정확히 같은지 검증한다. 메인·Viewer는
`config/egress_aisle.json`, crop replay·live는
`config/egress_aisle.pilot.json`을 사용한다.

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
`AISLE_BLOCK`은 OPEN 시 고정한 대표 AISLE의 `zoneId`를 함께 전송한다.

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
outbox publisher, evidence publication worker, 단일 monitoring thread와 optional
ToF runtime의 시작·정상 종료 생명주기를 소유한다. ToF를 활성화하면 actuator를
준비하고 monitoring 시작 뒤 authorization worker, sensor worker 순서로 시작한다.
종료 시 신규 ToF 입력을 막기 위해 sensor worker와 authorization worker를 먼저
정지한 뒤 monitoring·MoveVerification producer와 publication worker를 회수하고,
마지막으로 ToF projection을 비우고 speaker와 LED를 닫는다. 진행 중 durable
작업은 완료까지 기다리지만 queue 전체를 drain하지 않으며, 남은 durable 작업은
다음 기동의 recovery에서 이어간다.
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
GET  /live
GET  /live/stream
```

아래 데모 전용 두 엔드포인트(`GET /live`, `GET /live/stream`)를 제외한 모든
요청은 `X-Internal-API-Key`와 `Idempotency-Key`를 포함한다. API key는
local `.env`의 `INTERNAL_API_KEY`에만 저장하고 Git에는 넣지 않는다.

`GET /live`와 `GET /live/stream`은 라이브 시연 중 브라우저나 OBS로 판정
오버레이를 보기 위한 데모 전용 표면이며 `X-Internal-API-Key`를 요구하지
않는다. `LIVE_STREAM_ENABLED=true`일 때만 실제 오버레이 프레임을 낸다.
`GET /live`는 정적 뷰어 페이지라 설정과 무관하게 200을 반환하므로,
`LIVE_STREAM_ENABLED=false`에서는 그 페이지가 가리키는 `/live/stream`이
503으로 응답한다.
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
명시적으로 주입했을 때만 하나 기동한다. 기동 시 Evidence spool과
Monitoring durable state를 먼저 복구하고 camera·model open을 검증한다.
그 다음 parent Incident outbox publisher, child Evidence publisher를 순서대로
시작한 뒤에만 Monitoring·MoveVerification producer loop를 허용한다.
따라서 복구 중인 aggregate나 아직 Incident ACK가 없는 Evidence를
동시에 전송하지 않는다.

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
호출자에게 전달한다. `TOF_ENABLED=true`이고 core 설정이 완전하면
`src.main:app`은 듀얼 VL53L0X 점유, authorization worker와
`LocalWarningCoordinator`를 연결해 LED와 optional USB speaker에 전체 projection을
적용한다. monitoring frame commit과 Backend review·session context 적용은 활성
ToF 점유 구역의 권한 재평가를 요청하지만 그 자체로 경고를 켜지 않는다.

ToF 경고 상태는 process-local이며 durable Incident에서 복원하지 않는다.
구성·startup·actuator 실패는 ToF 또는 해당 장치에 격리되므로 FastAPI와 camera
monitoring이 계속 실행될 수 있다. 현재 `/health`는 SQLite durable admission만
확인하므로 ToF worker·sensor·LED·speaker의 정상 상태는 application log도 함께
확인해야 한다.

## PC 개발 환경에서 실행

`src.main:app`은 FastAPI와 함께 camera·tracking MonitoringWorker를 시작한다.
따라서 `.env`의 camera·calibration·model 및 MonitoringPolicy 설정이 유효해야
하며, asset preflight 또는 장치 open이 실패하면 서버 startup도 실패한다.
운영 camera pipeline은 `open()`에서 보정 frame 한 장을 캡처해 remap backend와
YOLO predictor/CUDA를 warm-up한 뒤 worker thread를 시작한다. 이 frame은
ByteTrack·PhysicalVehicle·주차 workflow에 전달하지 않으며 frame ID만 하나
소비한다. 리플레이 pipeline은 첫 기록 frame 보존을 위해 warm-up을 기본 생략한다.
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

## Jetson 경고 LED 배선 및 수동 진단

경고 LED adapter는 active-high 출력으로 동작한다.

```text
GPIO HIGH → LED ON
GPIO LOW → LED OFF
```

배선은 물리 BOARD 번호를 기준으로 한다.

```text
장애인 전용 구역 LED
BOARD Pin 31 → 1kΩ → LED 애노드 → LED 캐소드 → Pin 34 GND

전기차 충전 구역 LED
BOARD Pin 33 → 1kΩ → LED 애노드 → LED 캐소드 → Pin 34 GND
```

다음 사항을 함께 확인한다.

- Pin 31·33은 BCM이나 SoC 번호가 아닌 물리 BOARD 핀 번호다.
- `GPIO11`·`GPIO13` 문자열을 BCM 번호처럼 해석하지 않는다.
- Pin 15·29의 ToF XSHUT 배선 및 pinmux 설정과 혼동하지 않는다.
- 공통 GND는 물리 Pin 34를 사용한다.
- 우선 1kΩ 저항을 사용한다. 실제 시인성이 부족하면 LED 정격과 Jetson GPIO
  전기 사양을 다시 검토한 뒤 330Ω 사용을 검토한다.
- Pin 31·33은 실행 전에 GPIO output pinmux로 준비되어 있어야 한다.
- 정확한 설정 절차와 PADCTL 주소·값은 실물 검증 전까지 미확정이다. 보드,
  carrier 및 Jetson Linux 버전에 따라 달라질 수 있다.
- 진단 스크립트는 pinmux를 자동 변경하지 않으며 `sudo` 또는 `devmem`을
  자동 실행하지 않는다.
- 이 진단은 실제 Jetson에서만 실행한다.

현재 저장소에는 Pin 31·33에 대해 실물 검증된 PADCTL 주소와 raw 설정값이 없다.
위 ToF 절의 Pin 15·29용 `devmem` 명령은 LED 핀에 재사용하지 않는다.

실제 Jetson에서 다음 명령으로 진단한다.

```bash
cd hw/jetson
python -m scripts.check_warning_led
```

단계 유지 시간과 점멸 주기를 지정할 수도 있다.

```bash
python -m scripts.check_warning_led \
    --stage-seconds 3.0 \
    --off-seconds 1.0 \
    --blink-on-seconds 0.3 \
    --blink-off-seconds 0.3
```

진단은 다음 순서로 진행된다.

1. BOARD Pin 31·33을 LOW로 초기화한다.
2. 장애인 전용 구역 LED만 점멸한다.
3. 두 LED를 끈다.
4. 전기차 충전 구역 LED만 점멸한다.
5. 두 LED를 끈다.
6. 두 LED를 같은 phase로 동시에 점멸한다.
7. 두 LED를 끄고 worker와 GPIO 자원을 정리한다.

기본 stage, OFF 및 blink 시간은 수동 하드웨어 진단 편의값이며 운영 경고
정책이나 runtime settings가 아니다. GPIO write 또는 cleanup 실패가 확인되면
스크립트는 오류를 stderr에 출력하고 종료 코드 1을 반환한다.

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

`/health` 성공은 SQLite가 durable input을 접수할 수 있다는 뜻이며 ToF runtime,
sensor·authorization worker, LED 또는 speaker의 정상 상태를 보장하지 않는다.
별도 ToF health가 구현되기 전에는 application log에서 구성·시작·장치 실패를
함께 확인한다.

## 파일럿 영상 리플레이

§4.7 임계값과 MotionEstimator의 시간 창·정규화 evidence 기준을 산출하거나
회귀를 확인할 때는 녹화된 파일럿 영상을 새 파이프라인에 그대로 흘려보낼 수
있다.

```bash
python -m scripts.replay_pilot_video \
    --video ../../docs/video/video1.mp4 \
    --zones-file config/zone_definition.pilot.json \
    --egress-aisles-file config/egress_aisle.pilot.json \
    --calibration ../../ai/tracking/camera_calibration.json \
    --model-path ../../ai/training/yolo26n.pt \
    --zone-entry-confirm-seconds 3.0 --zone-exit-confirm-seconds 3.0 \
    --exit-reentry-confirmation-seconds 1.0 \
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
    --incident-disabled-zone-unauthorized-confirm-seconds 0.0 \
    --incident-disabled-zone-unauthorized-clear-seconds 0.0 \
    --incident-ev-zone-unauthorized-confirm-seconds 0.0 \
    --incident-ev-zone-unauthorized-clear-seconds 0.0 \
    --incident-ev-overstay-confirm-seconds 0.0 --incident-ev-overstay-clear-seconds 0.0 \
    --incident-bad-parking-confirm-seconds 0.5 --incident-bad-parking-clear-seconds 0.5 \
    --incident-out-of-zone-confirm-seconds 0.5 --incident-out-of-zone-clear-seconds 0.5 \
    --incident-aisle-block-confirm-seconds 0.5 --incident-aisle-block-clear-seconds 0.5 \
    --incident-double-parking-confirm-seconds 0.0 \
    --incident-double-parking-clear-seconds 0.0 \
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

# 537 YOLO 입력 좌우 마스킹 전처리 구현 인수인계

> 이 문서 전체를 구현 에이전트(Claude 등)에게 프롬프트로 전달한다.
> 현재 브랜치의 기존 커밋을 기준으로 작업하며, 아래 금지 범위와 완료 조건을
> 임의로 넓히거나 바꾸지 않는다.

## 1. 현재 기준 상태

- 작업 브랜치: `feature/ai/537-frame-side-mask-preprocessing`
- 기준 커밋: `ca5d9e7066929c524206d23da558137d988b9877`
  (`fix(ai): full-frame 구역 정의 정본 복구`)
- 기준 커밋에서 메인 Jetson과 Pipeline Viewer의 구역 정본은
  `hw/jetson/config/zone_definition.json` version 1이다.
- `zone_definition.json`은 crop 전 full-frame v5 폴리곤을 복구한 파일이다.
- 기준 파일 SHA-256:
  `A2476B4C8D937E11E034846FE16D74929BB8453B318FD56BDD10689D4776904A`
- `zone_definition.pilot.json` version 6과 `CropFrameSource`는 다른 작업자가
  소유한 crop 시연 경로다.

작업을 시작하기 전에 반드시 다음을 확인한다.

```bash
git branch --show-current
git status --short
git log -1 --oneline
```

기존 사용자 변경이 있으면 덮어쓰거나 되돌리지 않는다. 특히 기준 커밋을
`reset`, `restore`, `checkout --`, amend하지 않는다.

## 2. 목표

왜곡 보정된 full-frame의 크기와 좌표계를 그대로 유지하면서, YOLO에 전달되는
입력 복사본의 좌우 바깥 영역만 검정색으로 마스킹한다.

```text
CapturedFrame (remap 완료, 원본 유지)
    -> SideMaskingDetector (YOLO용 복사본의 좌우만 검정 마스킹)
    -> UltralyticsVehicleTracker
    -> YOLO + ByteTrack
```

마스킹은 crop이 아니다.

- 프레임 `width`/`height`를 바꾸지 않는다.
- bbox와 zone polygon의 정규화 좌표계를 바꾸지 않는다.
- `calibration_id`를 바꾸지 않는다.
- 모델 입력의 객체 크기나 종횡비를 바꾸지 않는다.
- 원본 `CapturedFrame.image`를 in-place로 수정하지 않는다.
- YOLO delegate에 넘기는 프레임 복사본만 마스킹한다.

## 3. 명시적 책임 경계

### 이번 작업 범위

- tracking 계층의 YOLO 입력 직전 마스킹 전처리 구현
- 순수 numpy 기반 좌우 마스크 처리
- `Detector` decorator 구현과 합성 배열 기반 단위 테스트
- full-frame을 사용하는 Pipeline Viewer detector 조립 경로에 적용
- 마스크 설정과 적용 사실을 코드·로그에서 확인 가능하게 유지

### 이번 작업 범위 밖

- 카메라 장치 adapter 또는 실제 배포 카메라 입력 조립
- `OpenCvWebcamFrameSource`, `VideoFileFrameSource`, `RemapFrameSource` 변경
- FastAPI `src/main.py`에 production camera/model factory 신규 구현
- YOLO 모델, 가중치, 학습 데이터 또는 학습 파이프라인 변경
- 재학습
- 영상 파일을 이용한 리플레이·정확도·성능 검증
- 렌더링 화면 crop 또는 별도의 시연 UI 변경

현재 저장소의 기본 FastAPI 앱은 camera/model factory가 주입되지 않으면
monitoring을 기동하지 않는다. 이 wiring은 다른 담당자의 범위다. 이번 작업은
그 담당자가 나중에 같은 `Detector` decorator를 조립할 수 있는 구현을 제공하되,
카메라 조립 코드를 대신 만들지 않는다.

## 4. 변경 금지 사항

다음 파일과 계약은 변경하지 않는다.

- `hw/jetson/config/zone_definition.json`
- `hw/jetson/config/zone_definition.pilot.json`
- `hw/jetson/scripts/recrop_zone_definition.py`
- `hw/jetson/src/camera/frame_source.py`의 기존 source/remap/crop 구현
- `hw/jetson/scripts/watch_live_stream.py`
- `hw/jetson/scripts/replay_pilot_video.py`
- `ai/tracking/replay_pilot_video.py`
- `ai/tracking/jetson_vehicle_tracking_baseline.py`
- `hw/jetson/.env.example`의
  `ZONE_DEFINITION_PATH=config/zone_definition.json`
- 메인 배포와 Pipeline Viewer가 `zone_definition.json`을 사용하도록 바꾼
  기준 커밋의 README·architecture 문서·테스트 경로
- `ai/tracking/pipeline_viewer/service.py`의
  `DEFAULT_ZONES_PATH = JETSON_ROOT / "config" / "zone_definition.json"`

`docs/superpowers/specs/2026-08-04-frame-margin-crop-design.md`는 530의 과거 crop
설계다. 이번 537의 요구사항으로 해석하거나 해당 문서를 수정·삭제하지 않는다.
특히 그 문서의 `crop_left_px=150`과 pilot v6 좌표를 이번 마스크에 적용하지 않는다.

## 5. 마스크 기하

현재 `zone_definition.json` version 1에서 1~9번 전체 polygon의 x좌표 합집합은
다음 범위다.

- 최소 x: `0.220`
- 최대 x: `0.768`

AISLE만 기준으로 계산하면 좌우 주차면을 침범하므로 반드시 전체 구역을 기준으로
한 아래 고정 경계를 사용한다.

- 왼쪽 마스크 끝: `0.180`
- 오른쪽 마스크 시작: `0.808`
- polygon 최외곽과 마스크 사이의 full-frame 여백: 좌우 각각 `0.040`
- 마스크 색상: RGB `(0, 0, 0)`

1920px 폭에서는 반올림 기준으로 대략 다음과 같다.

```text
[0, 346)       왼쪽 검정 마스크
[346, 1551)    가시 영역
[1551, 1920)   오른쪽 검정 마스크
```

경계 상수 이름은 의미가 드러나야 한다. 예:

```python
DEFAULT_LEFT_MASK_END_RATIO = 0.180
DEFAULT_RIGHT_MASK_START_RATIO = 0.808
```

두 값을 `left/right mask width`로 잘못 해석하지 않는다. 왼쪽 값은 x 경계이고,
오른쪽 값도 x 경계다.

## 6. 권장 구현 구조

### 신규 파일

`hw/jetson/src/tracking/adapters/side_masking_detector.py`

`src.tracking.protocols.Detector`를 구현하는 decorator를 만든다.

```python
class SideMaskingDetector:
    def __init__(
        self,
        *,
        inner: Detector,
        left_mask_end_ratio: float = DEFAULT_LEFT_MASK_END_RATIO,
        right_mask_start_ratio: float = DEFAULT_RIGHT_MASK_START_RATIO,
    ) -> None: ...

    @property
    def model_info(self) -> ModelInfo: ...

    def open(self) -> None: ...
    def track(self, frame: CapturedFrame) -> TrackerFrameResult: ...
    def close(self) -> None: ...
```

구현 규칙:

1. 생성 시 `0.0 <= left_mask_end_ratio < right_mask_start_ratio <= 1.0`을
   검증하고 위반 시 `ValueError`를 낸다.
2. `model_info`, `open()`, `close()`는 `inner`에 그대로 위임한다.
3. `track()`은 `frame.image`가 최소 `(H, W, C)` 형태이고 실제 크기가
   `frame.width`/`frame.height`와 일치하는지 확인한다.
4. 원본 배열을 수정하지 말고 `masked_image = frame.image.copy()`로 복사한다.
5. 픽셀 경계는 정규화 비율과 실제 폭에서 결정한다. 반올림 정책을 함수 하나에
   고정하고 테스트로 명시한다.
6. `masked_image[:, :left_end_px] = 0`,
   `masked_image[:, right_start_px:] = 0`을 적용한다.
7. `dataclasses.replace(frame, image=masked_image)`로 메타데이터가 동일한 새
   `CapturedFrame`을 만들고 `inner.track(masked_frame)`에 전달한다.
8. 가운데 가시 영역의 픽셀 값은 바이트 단위로 유지한다.
9. OpenCV나 Ultralytics에 의존하지 않는 numpy 처리로 구현한다.
10. 입력 배열 문제를 어떤 tracking 예외로 변환할지는 기존
    `UltralyticsVehicleTracker.track()`의 검증·`TrackingError` 정책과 맞춘다.

`UltralyticsVehicleTracker` 내부에 마스크 코드를 직접 넣지 않는다. 해당 tracker는
pilot v6 crop 리플레이에서도 사용하므로 기본 동작을 전역으로 바꾸면 좌표계가 다른
경로까지 잘못 마스킹한다. decorator를 선택적으로 조립해야 한다.

### Pipeline Viewer 조립

`ai/tracking/pipeline_viewer/service.py`에서만 현재 full-frame 검증 경로를 다음처럼
조립한다.

```python
raw_detector = UltralyticsVehicleTracker(...)
detector = SideMaskingDetector(inner=raw_detector)
```

`MonitoringDependencies(detector=detector)`에 wrapper를 넘긴다.

주의:

- `DEFAULT_ZONES_PATH`는 반드시 `zone_definition.json`으로 유지한다.
- 영상 source, `RemapFrameSource`, zone registry, calibration 검증은 변경하지 않는다.
- 입력 검증을 위해 별도로 생성하는 `UltralyticsVehicleTracker`가 있다면 불필요하게
  모델을 로드하거나 mask를 실행하지 않도록 현재 의미를 유지한다.
- production camera wiring은 추가하지 않는다.

## 7. 테스트 계획: 영상 사용 금지

영상 파일이 없는 환경을 전제로 한다. Desktop, Downloads, 외부 경로의 영상이나
스크린샷을 찾지 않는다. 영상 fixture를 새로 커밋하지 않는다.

신규 테스트 파일:

`hw/jetson/tests/test_side_masking_detector.py`

numpy 합성 배열과 fake `Detector`만 사용해 다음을 검증한다.

- 1920px 폭에서 정해진 반올림 정책대로 좌우 경계가 계산된다.
- 왼쪽과 오른쪽 영역이 모두 0으로 바뀐다.
- 가운데 영역은 원본과 바이트 단위로 동일하다.
- 입력 원본 배열은 변경되지 않는다.
- delegate가 받은 `CapturedFrame`의 `camera_id`, `frame_id`, `captured_at`,
  `width`, `height`, `calibration_id`가 원본과 동일하다.
- delegate의 반환값을 그대로 반환한다.
- `model_info`, `open()`, `close()`가 정확히 위임된다.
- 1920 이외의 폭에서도 정규화 비율로 동작한다.
- `left < 0`, `right > 1`, `left >= right`, NaN/무한대 입력을 거부한다.
- 잘못된 image shape 또는 metadata 불일치를 fail-closed로 거부한다.
- `SideMaskingDetector`를 사용하지 않은 raw detector의 기존 동작은 변하지 않는다.

가능하면 Pipeline Viewer의 서비스 테스트에 fake detector를 사용한 조립 검증을 한
개 추가한다. 실제 YOLO 모델과 실제 영상은 로드하지 않는다.

권장 실행 명령:

```bash
cd hw/jetson
python -m pytest tests/test_side_masking_detector.py -q
python -m pytest tests/test_ultralytics_bytetrack.py -q
cd ../..
python -m pytest ai/tracking/pipeline_viewer/tests/test_service.py -q
git diff --check
```

환경에 pytest 또는 기존 의존성이 없어 실행할 수 없다면 설치나 lockfile 변경을
임의로 하지 않는다. 실행하지 못한 명령과 이유를 최종 보고에 남기고, 최소한 변경된
Python 파일의 AST 구문 검사와 JSON 보호 파일 hash 검증은 수행한다.

## 8. 보호 파일 검증

구현 후 다음 파일들이 기준 커밋과 달라지지 않았는지 확인한다.

```bash
git diff --exit-code ca5d9e7 -- \
  hw/jetson/config/zone_definition.json \
  hw/jetson/config/zone_definition.pilot.json \
  hw/jetson/.env.example \
  hw/jetson/README.md \
  hw/jetson/config/README.md \
  docs/architecture/jetson/01-domain-purpose-and-output-contract.md \
  hw/jetson/tests/application/test_move_verification_round_trip.py \
  hw/jetson/tests/conftest.py \
  hw/jetson/tests/parking/test_zone_registry.py \
  hw/jetson/tests/test_main.py
```

추가로 다음을 확인한다.

```bash
git grep -n 'DEFAULT_ZONES_PATH = JETSON_ROOT / "config" / "zone_definition.json"' \
  -- ai/tracking/pipeline_viewer/service.py
```

`zone_definition.json` SHA-256도 기준값과 같아야 한다.

## 9. 완료 조건

- YOLO delegate가 받는 프레임 복사본에만 좌우 검정 마스크가 적용된다.
- 원본 프레임과 모든 좌표·메타데이터가 유지된다.
- Pipeline Viewer full-frame detector 경로가 wrapper를 사용한다.
- crop/pilot v6/카메라 입력/메인 map/기본 path는 변경되지 않는다.
- 실제 영상 없이 합성 배열 단위 테스트로 핵심 동작이 검증된다.
- 관련 테스트와 `git diff --check` 결과가 보고된다.
- 보호 파일 검증이 통과한다.
- 작업 범위 밖의 리팩터링, 문서 정리, dependency 변경을 하지 않는다.

## 10. 커밋 및 최종 보고

사용자 승인 없이 push하지 않는다. 커밋이 요청된 경우 AI 컨벤션을 따른다.

```text
feat(ai): YOLO 입력 좌우 마스킹 전처리 추가
```

최종 보고에는 다음을 포함한다.

1. 변경 파일과 구현 요약
2. 실제 실행한 테스트 명령과 결과
3. 실행하지 못한 검증과 이유
4. 보호 파일·기본 path·zone map 불변 확인
5. production 카메라 wiring과 영상 검증이 의도적으로 제외됐다는 사실

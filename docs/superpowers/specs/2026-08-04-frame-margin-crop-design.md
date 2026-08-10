# 프레임 좌우 여백 crop으로 화면 밖 오탐 제거 설계

> 이 문서는 `feature/ai/495-occupied-zone-overlay` 브랜치에서 처음 작성됐다가,
> Jira 530(`fix/ai/530-frame-margin-crop`)의 별도 작업으로 분리하면서 이
> 브랜치로 옮겼다. 옮기는 과정에서 `origin/develop`이 그 사이 진행돼
> `config/zone_definition.pilot.json`이 `zoneDefinitionVersion 3 -> 5`로,
> `calibrationReference`가 바뀐 것을 발견해 아래 수치를 그 기준으로 다시
> 실측·수정했다(원본 실측치는 동일 — 계산 오류가 아니라 base 파일이
> 바뀐 것).

## 배경

`docs/video/test_video_1,2,3.mp4`로 리플레이 테스트를 하던 중, 화면(주차 모형) 밖에 있는 사람의 신발(슬리퍼)이 반복적으로 "vehicle"로 오탐되는 문제가 발견됐다.

실측(`docs/calibration/camera_calibration.json` + balance 0.5로 remap한 뒤 YOLO(`vehicle_detector-yolov8s-20260729-153946/weights/best.pt`)를 1fps 샘플링으로 돌린 결과):

- 신발 오탐: test_video_2 3건(79s/89s/107s), test_video_3 4건(27s/41s/42s/45s), test_video_1은 0건. 전부 `x1≈0~113px`(정규화 0~0.059) 범위, confidence 0.50~0.63(모델 confidence 임계값 0.5 바로 위)으로 위치가 매우 일관됨 — 카메라 삼각대 옆에 서 있는 사람 발이 반복적으로 잡힌 것으로 추정.
- 오른쪽 여백에서는 이번 표본에서 오탐 근거가 없었다(0건).
- 같은 왼쪽 여백 근처에서 **실제** 모형 차량이 `x1=302px`(정규화 0.157)까지 들어온 정상 detection(confidence 0.89)도 관측됐다 — zone 1(현재 파일 기준 x범위 0.22~0.40 부근) 경계 근처에 있을 때 차량 bbox가 zone 경계보다 더 왼쪽으로 튀어나올 수 있다는 뜻이다.

즉 안전하게 제거할 수 있는 구간은 **113px~302px 사이**뿐이다. 이 여백을 프레임 자체에서 잘라내면(crop) 신발은 화면 밖으로 밀려나고, YOLO에 들어가는 이미지 폭도 줄어 Jetson 추론 비용이 함께 준다.

**calibration 파일 식별에 관한 메모**: `ai/tracking/camera_calibration.json`과 `docs/calibration/camera_calibration.json`은 K/D/image_size 값이 완전히 동일하다(파일 바이트 자체가 달라 SHA256 지문만 다르다 — 그래서 실측 결과도 두 파일 어느 쪽으로 remap하든 픽셀 단위로 동일하다). 하지만 `config/zone_definition.pilot.json`의 `calibrationReference`는 정확한 문자열 일치를 요구하므로(`monitoring_pipeline.py`의 `full_area_observed` 체크), 이후 스크립트·문서에서는 실제로 참조되는 `docs/calibration/camera_calibration.json` 쪽을 표준으로 쓴다.

## 범위

- 대상: `hw/jetson/src/camera/frame_source.py`(신규 `CropFrameSource`), `zone_definition.pilot.json`(좌표 재정규화), `hw/jetson/scripts/replay_pilot_video.py` / `watch_live_stream.py`(CLI 배선).
- 좌우 crop만 다룬다. 상하(top/bottom) crop은 이번 문제 범위가 아니라 다루지 않는다.
- crop을 마스킹(프레임 크기 유지, 여백만 검게 칠하기)으로 구현하는 대안은 검토했으나 기각했다 — 마스킹은 zone 파일을 안 건드려도 되는 대신 YOLO에 들어가는 이미지 크기가 그대로라 추론 속도 이득이 없다. 이번 목표(오탐 제거 + 성능)에는 실제 crop이 더 맞다.
- 모델을 신발 negative sample로 재학습하는 것은 별도 트랙이다. 이번 crop은 즉시 적용 가능한 기하학적 완화이며, 재학습을 대체하지 않는다.

## 변경 사항

### 1. `CropFrameSource` (신규)

```
VideoFileFrameSource / OpenCvWebcamFrameSource   (원본 프레임)
        → RemapFrameSource                       (fisheye 보정, calibration_id 부여)
        → CropFrameSource (신규)                  (좌우 여백 slice)
        → tracker(YOLO)
```

`RemapFrameSource`와 같은 `FrameSource` 프로토콜을 구현하고 다른 `FrameSource`를 감싸는 wrapper 패턴을 그대로 따른다.

```python
CropFrameSource(inner: FrameSource, crop_left_px: int = 0, crop_right_px: int = 0)
```

- `capture()`는 inner의 프레임을 받아 `image[:, crop_left_px : width - crop_right_px]`로 슬라이싱한다.
- `width`만 잘린 폭으로 갱신한다. `height`/`calibration_id`/`camera_id`/`frame_id`/`captured_at`은 그대로 통과시킨다.
  - `calibration_id`를 그대로 통과시켜도 되는 이유: `RemapFrameSource`가 채우는 `calibration_id`는 `calibration_fingerprint(calibration_path, balance)`의 해시로, 캘리브레이션 **파일** 자체의 지문이지 프레임 크기·좌표 범위와는 무관하다(`monitoring_pipeline.py`의 `full_area_observed` 체크도 이 fingerprint가 zones 파일의 `calibrationReference`와 일치하는지만 본다). 따라서 crop을 껴 넣어도 캘리브레이션 재작업이나 fingerprint 재계산이 필요 없다.
- 기본값 `0/0`이면 완전 no-op(원본과 픽셀 단위로 동일) — 기존 배포·테스트는 아무 것도 안 바뀐다.

**에러 처리**

- 생성 시점: `crop_left_px < 0` 또는 `crop_right_px < 0`이면 `ValueError` (`UltralyticsVehicleTracker` 등 기존 생성자들과 동일한 즉시 검증 스타일).
- `capture()` 시점: `crop_left_px + crop_right_px >= width`(잘라내면 폭이 0 이하)면 `FrameSourceError(state=DEGRADED, reason=PARTIAL_FRAME)` — `RemapFrameSource._frame_size`의 빈 프레임 가드와 동일한 패턴.

### 2. zone 좌표 재정규화 (`hw/jetson/scripts/recrop_zone_definition.py`, 신규)

일회성 마이그레이션이지만 crop 값이 나중에 다시 바뀔 수 있어 재사용 가능한 스크립트로 남긴다.

`zone_definition.pilot.json`을 읽어 모든 polygon x좌표에 다음을 적용한다(y좌표는 변경 없음):

```
new_x = (old_x * old_width - crop_left_px) / new_width
new_width = old_width - crop_left_px - crop_right_px
```

- `zoneDefinitionVersion`을 1 올린다(파일에 실제로 기록된 현재 값 기준 +1 — 하드코딩하지 않는다).
- `calibrationReference`는 그대로 유지한다 — crop은 calibration_id에 영향을 주지 않으므로(§1) 값이 바뀔 이유가 없다.
- 결과 폴리곤이 여전히 `[0, 1]` 범위 안에 있는지 검증하고, 벗어나면(즉 crop이 기존 zone을 침범하면) 에러를 내고 파일을 쓰지 않는다.

### 3. CLI 배선

`replay_pilot_video.py`, `watch_live_stream.py`에 `--crop-left-px`/`--crop-right-px`(기본값 `0`, 즉 기본은 no-op) 옵션을 추가하고, `RemapFrameSource` 뒤에 `CropFrameSource`를 끼워 넣는다.

### 4. 실측값

이번 실측 기준 권장값은 `crop_left_px=150`, `crop_right_px=0`이다(신발 최대 관측 113px에 여유를 두면서 실차량 최소 관측 302px는 침범하지 않는 지점). 오른쪽은 이번 표본에서 오탐 근거가 없어 자르지 않는다.

이 값은 이번 실측(test_video_1,2,3, 1fps 샘플링)에 근거한 잠정치다 — 실제 배포 전 더 긴 리허설 영상으로 재검증을 권장한다.

구현 시점의 `config/zone_definition.pilot.json` 실제 `zoneDefinitionVersion`을 확인하고 그 값 기준으로 +1 하여 적용한다(이 문서 작성 시점엔 5였지만, 브랜치 분기 전에 다시 확인이 필요하다).

### 5. 테스트

`hw/jetson/tests/test_remap_frame_source.py`의 "알려진 기하로 검증" 방식을 그대로 따른다(`test_crop_frame_source.py` 신규).

- 알려진 위치에 마커 픽셀을 심은 이미지 → crop 후 마커가 예상 좌표로 이동했는지 확인.
- `crop_left_px=0, crop_right_px=0`이면 원본과 픽셀 단위로 동일(no-op) 확인.
- `width`만 줄고 `height`/`calibration_id`/`camera_id`/`frame_id`/`captured_at`은 그대로인지 확인.
- crop 합이 폭 이상일 때 `FrameSourceError(DEGRADED, PARTIAL_FRAME)` 확인.
- 음수 crop 값에 `ValueError` 확인.
- `open()`/`close()`가 inner로 위임되는지 확인.

`recrop_zone_definition.py`용 golden-file 테스트(신규):

- 알려진 crop 값으로 임의의 샘플 payload를 변환했을 때 폴리곤 좌표가 정확한 새 값으로 나오는지 확인(실제 파일 값에 의존하지 않는 고정 fixture 사용).
- `zoneDefinitionVersion`은 +1, `calibrationReference`는 원본과 동일한지 확인.
- 변환 후 폴리곤 좌표가 `[0, 1]` 범위를 벗어나면 에러를 내고 파일을 쓰지 않는지 확인.

## 비범위 / 명시적 제외

- 상하(top/bottom) crop: 이번 문제 범위가 아니다. 필요해지면 별도 설계.
- 마스킹(프레임 크기 유지, 여백만 검게 칠하기): 추론 속도 이득이 없어 기각.
- YOLO 모델 재학습(신발 negative sample 추가): 별도 트랙, 이번 crop이 그 작업의 필요성을 없애지 않는다.
- `zone_definition.webcam_test.json` 갱신: 이번 실측이 pilot 캘리브레이션 기준이라 범위 밖. webcam_test용 crop이 필요하면 별도 실측·설계가 필요하다.
- production 카메라 배선(`src/main.py`)에 `CropFrameSource` 연결: 아직 실제 카메라 adapter 자체가 배선되지 않은 상태(`monitoring_pipeline_factory`가 배포 계층 몫)라 이번 범위 밖. replay/webcam 스크립트에만 배선한다.

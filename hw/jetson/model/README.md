# Jetson Tracking Model

운영 차량 탐지 모델은 Ultralytics가 배포하는 스톡 COCO 사전학습
`yolov8s.pt`가 아니다. 파일명이 같아 혼동하기 쉽지만, 이 프로젝트가
차량(vehicle) 단일 클래스로 파인튜닝한 가중치를 같은 파일명으로 배치해
쓰는 것뿐이다. 스톡 모델을 그 경로에 잘못 놓아도 애플리케이션은 정상
기동하고 COCO `car` 클래스로 어느 정도 차량을 잡기 때문에, 아래 검증
절차 없이는 잘못 배치된 사실을 알아채기 어렵다.

## 출처 (584)

운영 모델은 다음 학습 run의 산출물이다.

```text
run     vehicle_detector-yolov8s-20260804-222535
원본    ai/training/runs/detect/runs/train/vehicle_detector-yolov8s-20260804-222535/weights/best.pt
크기    22513187 bytes
sha256  3ac438bb2378ded109329a4d3efd610419b695f09fa47817e34045dc09ab7b5d
클래스  nc: 1, names: [vehicle]  (출처: ai/training/data/processed/vehicle/data.yaml)
```

저장소의 다른 스크립트(`replay_pilot_video.py`, `watch_live_stream.py`,
`extract_undetected_frames.py`, `analyze_video_replay.py` 등)가 예시나
기본값으로 가리키는 학습 run도 위와 같아야 한다. 다른 run을 가리키면
프레임 뷰어로 확인한 결과와 젯슨 실제 동작이 서로 다른 모델에서 나올 수
있으므로 어긋난 참조를 발견하면 위 run으로 맞춘다.

## 배치 경로

저장소 checkout에서는 다음 위치를 사용한다.

```text
hw/jetson/model/yolov8s.pt
hw/jetson/model/vehicle_model_manifest.json
```

Jetson 배포 시에는 다음 절대경로에 같은 파일을 배치한다.

```text
/home/e202/model/yolov8s.pt
/home/e202/model/vehicle_model_manifest.json
```

모델 가중치는 Git에 포함하지 않지만 manifest는 Git에서 버전
관리한다. Jetson 기동 전에 해당 환경의 경로에 위 출처의
`yolov8s.pt`와 같은 release의 manifest를 함께 배치해야 한다.
`.env`의 `VEHICLE_MODEL_MANIFEST_PATH`는 배치한 manifest 경로를
가리켜야 한다.

## 기동 시 자동 검증

Monitoring composition은 camera·YOLO 객체를 만들기 전에 manifest의
`schemaVersion`, `modelVersion`, `sha256`, `task`, `classNames`를 검증한다.
Binary SHA-256이 일치하지 않으면 기동을 중단한다. Binary를 로드한
후에도 Ultralytics runtime의 `task == 'detect'`와 class map
`{0: 'vehicle'}`를 재검증한다. 실제 tracking 호출은 `classes=[0]`을
명시해 차량 단일 클래스만 ByteTrack에 전달한다.

Manifest SHA preflight은 운영 `src.main` composition root의 release 고정
책임이다. `replay_pilot_video.py`, `watch_live_stream.py`, Pipeline Viewer는
차량 단일 클래스의 다른 학습 run도 비교할 수 있도록 manifest 경로를 받지
않는다. 이 개발·진단 경로에도 tracker의 task·class map 검증과
`classes=[0]` runtime 계약은 동일하게 적용된다.

## 배치한 파일이 맞는지 확인하는 방법

아래 명령은 기동 실패 원인을 배포 환경에서 직접 재현할 때
사용한다. 정상 기동 경로에서는 위 자동 검증이 같은 계약을
강제한다.

### 1. sha256 대조

```bash
sha256sum /home/e202/model/yolov8s.pt
```

결과가 위 출처의 `3ac438bb2378ded109329a4d3efd610419b695f09fa47817e34045dc09ab7b5d`와
정확히 같아야 한다. 다르면 다른 run의 가중치이거나 스톡 모델이 잘못
놓인 것이다.

### 2. 클래스 정의 대조

```bash
python -c "from ultralytics import YOLO; print(YOLO('/home/e202/model/yolov8s.pt').names)"
```

`{0: 'vehicle'}` 하나만 나와야 한다. COCO 80개 클래스(`{0: 'person', 1:
'bicycle', 2: 'car', ...}`)가 나오면 스톡 사전학습 모델이 잘못 배치된
것이므로 즉시 교체한다.

두 확인 중 하나라도 기대와 다르면 애플리케이션을 기동하지 않고 위 출처
경로에서 올바른 가중치를 다시 배치한다.

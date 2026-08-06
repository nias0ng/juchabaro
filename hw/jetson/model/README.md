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
```

Jetson 배포 시에는 다음 절대경로에 같은 파일을 배치한다.

```text
/home/e202/model/yolov8s.pt
```

모델 가중치는 Git에 포함하지 않는다. Viewer 실행 또는 Jetson 기동 전에
해당 환경의 경로에 위 출처의 `yolov8s.pt`를 직접 배치해야 한다.

## 배치한 파일이 맞는지 확인하는 방법

파일명만으로는 스톡 COCO 모델과 파인튜닝 모델을 구분할 수 없으므로,
배치 후 반드시 아래 두 가지를 확인한다.

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

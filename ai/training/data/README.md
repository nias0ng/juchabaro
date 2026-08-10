# 데이터 안내

## 차량 탐지 (`configs/yolo_vehicle.yaml`)

CVAT `vehicle-detection` 프로젝트에서 Task 단위로 **`Ultralytics YOLO Detection 1.0`** 포맷 +
이미지 포함으로 export한 zip들을 `data/raw/vehicle/`(gitignore됨)에 모아두고,
`scripts/build_vehicle_dataset.py`로 하나의 train/val 데이터셋(`data/processed/vehicle/`,
gitignore됨)으로 합친다. 여러 Task가 같은 영상에서 나온 경우가 있어 **Task(영상) 단위로
통째로 train 또는 val에 배정**한다 — 인접 프레임이 양쪽에 섞이는 data leakage를 막기 위해
([차량 탐지 라벨링 가이드 §5](../../../docs/차량%20탐지%20라벨링%20가이드.md#5-데이터-분할)).

```
uv run --with-requirements requirements.txt python scripts/build_vehicle_dataset.py \
  --raw-dir data/raw/vehicle --output data/processed/vehicle --val-tasks 8,9
```

`--val-tasks`는 val로 뺄 CVAT task id 목록(쉼표 구분, 기본값 `8,9`). Task는 프레임당 차량 수
기준으로 한쪽에 쏠려있는 경우가 많다(예: task4/7/8은 90%+가 2대 이상, task9/10은 90%+가 1대) —
val을 task8 하나로만 잡으면 검증셋이 거의 전부 "2대 이상" 프레임이 되어 "1대(정상주차)" 조건의
성능을 사실상 검증하지 못한다. task8(2대 위주) + task9(1대 위주)를 같이 val로 묶어야 전체
풀의 1대:2대 비율(약 33:65)에 가까운, 대표성 있는 val이 나온다.

`configs/yolo_vehicle.yaml`의 `data:`는
이 스크립트가 만든 `data/processed/vehicle/data.yaml`을 가리킨다. 실데이터가 없으면
Ultralytics 내장 `coco8.yaml`(이미지 8장, 최초 실행 시 자동 다운로드)로 되돌려 스모크 테스트용으로 쓸 수 있다.

## 번호판 검출 (`configs/yolo_plate.yaml`)

`scripts/make_plate_smoke_dataset.py`가 생성한 합성 데이터(`data/samples/plate/`)를
기본값으로 사용한다. 이 데이터는 학습 루프 동작 검증용이며 정확도는 무의미하다.
실데이터(AI Hub 변환본 또는 CVAT export)가 준비되면 `configs/yolo_plate.yaml`의
`data:` 값만 실데이터의 `data.yaml` 경로로 바꾼다.

번호판 검출은 pose 태스크다(원근 왜곡 보정을 위해 4코너 keypoint를 함께 검출 — [AI 설계
§1.1](../../../docs/superpowers/specs/2026-07-22-smart-parking-ai-design.md#11-개정-번호판-검출-모델--yolov8n-pose-2026-07-24)).
실데이터 라벨에도 bbox(`class cx cy w h`) 뒤에 4개 코너 좌표(`x1 y1 x2 y2 x3 y3 x4 y4`, 좌상→우상→우하→좌하
순서)가 있어야 하고, `data.yaml`에 `kpt_shape: [4, 2]`를 포함해야 한다. CVAT에서 export할 때
bbox가 아닌 skeleton/points 라벨링으로 4개 코너를 함께 찍어야 한다.

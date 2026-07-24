# 데이터 안내

## 차량 탐지 (`configs/yolo_vehicle.yaml`)

기본값은 Ultralytics 내장 `coco8.yaml`(이미지 8장)이며 최초 실행 시 자동 다운로드된다.
실데이터로 전환하려면 `configs/yolo_vehicle.yaml`의 `data:` 값을 Ultralytics 표준 형식
(`path`, `train`, `val`, `nc`, `names`)의 데이터셋 YAML 경로로 바꾼다.

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

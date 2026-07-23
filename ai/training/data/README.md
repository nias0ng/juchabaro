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

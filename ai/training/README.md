# ai/training

차량 탐지·번호판 검출 YOLO 모델 학습 파이프라인 (스마트 주차장 AI, AI1 담당).

## 빠른 시작

```bash
uv venv ai/training/.venv --python 3.12
uv pip install --python ai/training/.venv -r ai/training/requirements.txt
```

## 학습 실행

```bash
cd ai/training
python scripts/train_yolo.py --config configs/yolo_vehicle.yaml
python scripts/train_yolo.py --config configs/yolo_plate.yaml
```

모델 크기를 바꿔 실험하려면 `--base-model`을 오버라이드한다:

```bash
python scripts/train_yolo.py --config configs/yolo_vehicle.yaml --base-model yolov8m.pt
```

## 테스트

```bash
python -m pytest tests -v
```

## 데이터

실데이터 투입 방법은 [data/README.md](data/README.md)를 참고한다.

## 범위 밖

모델 경량화·변환(ONNX/TensorRT)과 PaddleOCR 파인튜닝은 이 파이프라인의 범위가 아니다.

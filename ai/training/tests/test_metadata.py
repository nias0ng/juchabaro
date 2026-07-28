import json
from datetime import datetime
from pipeline.metadata import write_model_meta


def test_write_model_meta_creates_expected_json(tmp_path):
    output_path = write_model_meta(
        weights_dir=str(tmp_path / "weights"),
        model_name="vehicle_detector",
        model_version="vehicle_detector-yolov8s-20260722-143200",
        base_model="yolov8s.pt",
        dataset="coco8.yaml",
        hyperparams={"epochs": 50, "imgsz": 640, "batch": 16},
        metrics={"mAP50": 0.5, "mAP50-95": 0.3},
        commit_hash="3f3e4b2",
        trained_at=datetime(2026, 7, 22, 14, 32, 0),
    )

    with open(output_path) as f:
        meta = json.load(f)

    assert meta["model_name"] == "vehicle_detector"
    assert meta["model_version"] == "vehicle_detector-yolov8s-20260722-143200"
    assert meta["commit_hash"] == "3f3e4b2"
    assert meta["trained_at"] == "2026-07-22T14:32:00"
    assert meta["metrics"]["mAP50"] == 0.5
    assert meta["hyperparams"]["batch"] == 16

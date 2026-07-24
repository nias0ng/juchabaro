import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from train_yolo import build_arg_parser, run_training, main


def test_build_arg_parser_parses_required_and_optional_args():
    parser = build_arg_parser()

    args = parser.parse_args(["--config", "configs/yolo_vehicle.yaml", "--base-model", "yolov8m.pt"])

    assert args.config == "configs/yolo_vehicle.yaml"
    assert args.base_model == "yolov8m.pt"
    assert args.epochs is None
    assert args.version is None


def test_run_training_orchestrates_config_train_and_metadata(tmp_path, monkeypatch):
    config_file = tmp_path / "yolo_vehicle.yaml"
    config_file.write_text(
        "model_name: vehicle_detector\n"
        "base_model: yolov8s.pt\n"
        "data: coco8.yaml\n"
        "epochs: 1\n"
        "imgsz: 640\n"
        "batch: 16\n"
        "project: smart-parking-ai\n"
    )
    monkeypatch.chdir(tmp_path)

    fake_results = MagicMock()
    fake_results.results_dict = {"metrics/mAP50(B)": 0.42, "metrics/mAP50-95(B)": 0.21}
    fake_results.save_dir = str(tmp_path / "runs" / "train" / "vehicle_detector-yolov8s-20260722-143200")
    fake_model = MagicMock()
    fake_model.train.return_value = fake_results

    with patch("train_yolo.YOLO", return_value=fake_model) as mock_yolo_cls, \
         patch("train_yolo.wandb") as mock_wandb, \
         patch("train_yolo.get_commit_hash", return_value="3f3e4b2"):
        result = run_training(str(config_file), version="vehicle_detector-yolov8s-20260722-143200")

    mock_yolo_cls.assert_called_once_with("yolov8s.pt")
    fake_model.train.assert_called_once_with(
        data="coco8.yaml", epochs=1, imgsz=640, batch=16, device="",
        project="runs/train", name="vehicle_detector-yolov8s-20260722-143200",
    )
    mock_wandb.init.assert_called_once()
    mock_wandb.finish.assert_called_once()

    expected_weights_dir = Path(fake_results.save_dir) / "weights"
    assert result["model_version"] == "vehicle_detector-yolov8s-20260722-143200"
    assert Path(result["meta_path"]).exists()
    assert Path(result["meta_path"]).name == "model_meta.json"
    assert result["best_weights"] == str(expected_weights_dir / "best.pt")


def test_run_training_captures_pose_metrics_when_present(tmp_path, monkeypatch):
    config_file = tmp_path / "yolo_plate.yaml"
    config_file.write_text(
        "model_name: plate_detector\n"
        "base_model: yolov8n-pose.pt\n"
        "data: data/samples/plate/data.yaml\n"
        "epochs: 1\n"
        "imgsz: 640\n"
        "batch: 16\n"
        "project: smart-parking-ai\n"
    )
    monkeypatch.chdir(tmp_path)

    fake_results = MagicMock()
    fake_results.results_dict = {
        "metrics/mAP50(B)": 0.42,
        "metrics/mAP50-95(B)": 0.21,
        "metrics/mAP50(P)": 0.35,
        "metrics/mAP50-95(P)": 0.18,
    }
    fake_results.save_dir = str(tmp_path / "runs" / "train" / "plate_detector-yolov8n-pose-20260724-000000")
    fake_model = MagicMock()
    fake_model.train.return_value = fake_results

    with patch("train_yolo.YOLO", return_value=fake_model), \
         patch("train_yolo.wandb"), \
         patch("train_yolo.get_commit_hash", return_value="3f3e4b2"):
        result = run_training(str(config_file), version="plate_detector-yolov8n-pose-20260724-000000")

    meta = json.loads(Path(result["meta_path"]).read_text())
    assert meta["metrics"]["mAP50"] == 0.42
    assert meta["metrics"]["mAP50-95"] == 0.21
    assert meta["metrics"]["pose_mAP50"] == 0.35
    assert meta["metrics"]["pose_mAP50-95"] == 0.18


def test_run_training_omits_pose_metrics_for_plain_detect(tmp_path, monkeypatch):
    config_file = tmp_path / "yolo_vehicle.yaml"
    config_file.write_text(
        "model_name: vehicle_detector\n"
        "base_model: yolov8s.pt\n"
        "data: coco8.yaml\n"
        "epochs: 1\n"
        "imgsz: 640\n"
        "batch: 16\n"
        "project: smart-parking-ai\n"
    )
    monkeypatch.chdir(tmp_path)

    fake_results = MagicMock()
    fake_results.results_dict = {"metrics/mAP50(B)": 0.42, "metrics/mAP50-95(B)": 0.21}
    fake_results.save_dir = str(tmp_path / "runs" / "train" / "vehicle_detector-yolov8s-20260724-000000")
    fake_model = MagicMock()
    fake_model.train.return_value = fake_results

    with patch("train_yolo.YOLO", return_value=fake_model), \
         patch("train_yolo.wandb"), \
         patch("train_yolo.get_commit_hash", return_value="3f3e4b2"):
        result = run_training(str(config_file), version="vehicle_detector-yolov8s-20260724-000000")

    meta = json.loads(Path(result["meta_path"]).read_text())
    assert "pose_mAP50" not in meta["metrics"]
    assert "pose_mAP50-95" not in meta["metrics"]


def test_run_training_generates_version_when_not_given(tmp_path, monkeypatch):
    config_file = tmp_path / "yolo_vehicle.yaml"
    config_file.write_text(
        "model_name: vehicle_detector\n"
        "base_model: yolov8s.pt\n"
        "data: coco8.yaml\n"
        "epochs: 1\n"
        "imgsz: 640\n"
        "batch: 16\n"
        "project: smart-parking-ai\n"
    )
    monkeypatch.chdir(tmp_path)

    fake_results = MagicMock()
    fake_results.results_dict = {}
    fake_results.save_dir = str(tmp_path / "runs" / "train" / "vehicle_detector-yolov8m-generated")
    fake_model = MagicMock()
    fake_model.train.return_value = fake_results

    with patch("train_yolo.YOLO", return_value=fake_model), \
         patch("train_yolo.wandb"), \
         patch("train_yolo.get_commit_hash", return_value="unknown"):
        result = run_training(str(config_file), base_model="yolov8m.pt")

    assert result["model_version"].startswith("vehicle_detector-yolov8m-")
    expected_weights_dir = Path(fake_results.save_dir) / "weights"
    assert result["best_weights"] == str(expected_weights_dir / "best.pt")
    assert Path(result["meta_path"]).exists()
    assert Path(result["meta_path"]).name == "model_meta.json"


def test_main_runs_end_to_end_with_mocked_training(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "yolo_vehicle.yaml"
    config_file.write_text(
        "model_name: vehicle_detector\n"
        "base_model: yolov8s.pt\n"
        "data: coco8.yaml\n"
        "epochs: 1\n"
        "imgsz: 640\n"
        "batch: 16\n"
        "project: smart-parking-ai\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["train_yolo.py", "--config", str(config_file), "--version", "vehicle_detector-yolov8s-20260722-999999"],
    )

    fake_results = MagicMock()
    fake_results.results_dict = {}
    fake_results.save_dir = str(tmp_path / "runs" / "detect" / "vehicle_detector-yolov8s-20260722-999999")
    fake_model = MagicMock()
    fake_model.train.return_value = fake_results

    with patch("train_yolo.YOLO", return_value=fake_model), patch("train_yolo.wandb"):
        main()

    captured = capsys.readouterr()
    assert "vehicle_detector-yolov8s-20260722-999999" in captured.out
    assert "best.pt" in captured.out

import yaml
import pytest
from pipeline.config import load_config


def _write_config(tmp_path, overrides=None):
    config = {
        "model_name": "vehicle_detector",
        "base_model": "yolov8s.pt",
        "data": "coco8.yaml",
        "epochs": 50,
        "imgsz": 640,
        "batch": 16,
        "project": "smart-parking-ai",
    }
    if overrides:
        config.update(overrides)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config))
    return config_file


def test_load_config_reads_yaml_and_defaults_device(tmp_path):
    config_file = _write_config(tmp_path)

    config = load_config(str(config_file))

    assert config["model_name"] == "vehicle_detector"
    assert config["base_model"] == "yolov8s.pt"
    assert config["device"] == ""


def test_load_config_applies_non_none_overrides_only(tmp_path):
    config_file = _write_config(tmp_path)

    config = load_config(str(config_file), overrides={"base_model": "yolov8m.pt", "epochs": None})

    assert config["base_model"] == "yolov8m.pt"
    assert config["epochs"] == 50


def test_load_config_raises_on_missing_required_keys(tmp_path):
    config_file = tmp_path / "bad.yaml"
    config_file.write_text(yaml.safe_dump({"model_name": "x"}))

    with pytest.raises(ValueError, match="Missing required config keys"):
        load_config(str(config_file))


def test_load_config_raises_value_error_on_empty_yaml_file(tmp_path):
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("")

    with pytest.raises(ValueError, match="Missing required config keys"):
        load_config(str(config_file))

from __future__ import annotations
import yaml

REQUIRED_KEYS = ("model_name", "base_model", "data", "epochs", "imgsz", "batch", "project")


def load_config(config_path: str, overrides: dict | None = None) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config.setdefault("device", "")

    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")

    if overrides:
        for key, value in overrides.items():
            if value is not None:
                config[key] = value

    return config

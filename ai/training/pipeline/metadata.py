from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path


def write_model_meta(
    weights_dir: str,
    model_name: str,
    model_version: str,
    base_model: str,
    dataset: str,
    hyperparams: dict,
    metrics: dict,
    commit_hash: str,
    trained_at: datetime | None = None,
) -> str:
    ts = trained_at or datetime.now()
    meta = {
        "model_name": model_name,
        "model_version": model_version,
        "base_model": base_model,
        "dataset": dataset,
        "hyperparams": hyperparams,
        "metrics": metrics,
        "commit_hash": commit_hash,
        "trained_at": ts.isoformat(),
    }

    output_path = Path(weights_dir) / "model_meta.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return str(output_path)

from __future__ import annotations
import subprocess
from datetime import datetime
from pathlib import Path


def generate_model_version(model_name: str, base_model: str, timestamp: datetime | None = None) -> str:
    ts = timestamp or datetime.now()
    base_model_stem = Path(base_model).stem
    return f"{model_name}-{base_model_stem}-{ts.strftime('%Y%m%d-%H%M%S')}"


def get_commit_hash(cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"

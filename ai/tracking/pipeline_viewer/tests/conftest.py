"""Pipeline Viewer 테스트의 저장소 import 경로."""

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
for path in (
    REPOSITORY_ROOT / "ai" / "tracking",
    REPOSITORY_ROOT / "hw" / "jetson",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

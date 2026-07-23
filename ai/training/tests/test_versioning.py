import subprocess
from datetime import datetime
from pipeline.versioning import generate_model_version, get_commit_hash


def test_generate_model_version_format():
    ts = datetime(2026, 7, 22, 14, 32, 0)

    version = generate_model_version("vehicle_detector", "yolov8s.pt", timestamp=ts)

    assert version == "vehicle_detector-yolov8s-20260722-143200"


def test_get_commit_hash_returns_unknown_outside_git_repo(tmp_path):
    assert get_commit_hash(cwd=str(tmp_path)) == "unknown"


def test_get_commit_hash_returns_short_hash_inside_git_repo(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    commit_hash = get_commit_hash(cwd=str(tmp_path))

    assert commit_hash != "unknown"
    assert len(commit_hash) == 7

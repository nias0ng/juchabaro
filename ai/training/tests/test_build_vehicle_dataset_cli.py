import sys
import zipfile
from pathlib import Path


def _write_task_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("images/train/a.jpg", b"imgA")
        archive.writestr("labels/train/a.txt", "0 0.5 0.5 0.2 0.2\n")


def test_main_builds_dataset_via_cli(tmp_path, monkeypatch, capsys):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_task_zip(raw_dir / "dataset_task_2.zip")

    output_dir = tmp_path / "processed"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_vehicle_dataset.py",
            "--raw-dir", str(raw_dir),
            "--output", str(output_dir),
            "--val-tasks", "8",
        ],
    )

    from build_vehicle_dataset import main

    main()

    captured = capsys.readouterr()
    assert str(output_dir) in captured.out
    assert (output_dir / "data.yaml").exists()
    assert (output_dir / "images" / "task2_a.jpg").exists()

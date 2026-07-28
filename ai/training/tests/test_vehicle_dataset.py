import zipfile
from pathlib import Path

import yaml
from pipeline.vehicle_dataset import build_vehicle_dataset


def _write_task_zip(zip_path: Path, images: dict[str, bytes], labels: dict[str, str]) -> None:
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("data.yaml", "names:\n  0: vehicle\npath: .\ntrain: train.txt\n")
        for name, content in images.items():
            archive.writestr(f"images/train/{name}", content)
        for name, content in labels.items():
            archive.writestr(f"labels/train/{name}", content)


def test_build_vehicle_dataset_merges_and_splits_by_task(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    _write_task_zip(
        raw_dir / "dataset_task_2.zip",
        images={"a.jpg": b"imgA", "b.jpg": b"imgB"},
        labels={"a.txt": "0 0.5 0.5 0.2 0.2\n"},  # b.jpg has no label -> background frame
    )
    _write_task_zip(
        raw_dir / "dataset_task_8.zip",
        images={"c.jpg": b"imgC"},
        labels={"c.txt": "0 0.4 0.4 0.1 0.1\n"},
    )

    output_dir = tmp_path / "processed"
    data_yaml_path = build_vehicle_dataset(str(raw_dir), str(output_dir), val_tasks=[8])

    train_files = (output_dir / "train.txt").read_text().splitlines()
    val_files = (output_dir / "val.txt").read_text().splitlines()
    assert train_files == ["./images/task2_a.jpg", "./images/task2_b.jpg"]
    assert val_files == ["./images/task8_c.jpg"]

    assert (output_dir / "images" / "task2_a.jpg").read_bytes() == b"imgA"
    assert (output_dir / "images" / "task2_b.jpg").exists()
    assert not (output_dir / "labels" / "task2_b.txt").exists()
    assert (output_dir / "labels" / "task2_a.txt").read_text() == "0 0.5 0.5 0.2 0.2\n"
    assert (output_dir / "labels" / "task8_c.txt").read_text() == "0 0.4 0.4 0.1 0.1\n"

    with open(data_yaml_path) as f:
        data_yaml = yaml.safe_load(f)
    assert data_yaml["nc"] == 1
    assert data_yaml["names"] == ["vehicle"]
    assert data_yaml["train"] == "train.txt"
    assert data_yaml["val"] == "val.txt"


def test_build_vehicle_dataset_raises_on_unrecognized_filename(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_task_zip(raw_dir / "mystery.zip", images={"a.jpg": b"imgA"}, labels={})

    try:
        build_vehicle_dataset(str(raw_dir), str(tmp_path / "processed"), val_tasks=[8])
        assert False, "expected ValueError"
    except ValueError:
        pass

from __future__ import annotations
import re
import zipfile
from pathlib import Path

import yaml

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
TASK_ID_PATTERN = re.compile(r"task_?(\d+)")


def build_vehicle_dataset(raw_dir: str, output_dir: str, val_tasks: list[int]) -> str:
    """Merge CVAT `Ultralytics YOLO Detection` task exports (zips) into one train/val dataset.

    Whole tasks are assigned to train or val (never split within a task/video) to
    avoid leaking adjacent frames from the same video across the split.
    """
    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    images_dir = output_path / "images"
    labels_dir = output_path / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    train_files: list[str] = []
    val_files: list[str] = []

    for zip_path in sorted(raw_path.glob("*.zip")):
        match = TASK_ID_PATTERN.search(zip_path.stem)
        if not match:
            raise ValueError(f"Cannot determine CVAT task id from filename: {zip_path.name}")
        task_id = int(match.group(1))
        split_files = val_files if task_id in val_tasks else train_files

        with zipfile.ZipFile(zip_path) as archive:
            image_entries = {
                Path(name).stem: name
                for name in archive.namelist()
                if name.startswith("images/train/") and Path(name).suffix.lower() in IMAGE_EXTENSIONS
            }
            label_entries = {
                Path(name).stem: name
                for name in archive.namelist()
                if name.startswith("labels/train/") and name.endswith(".txt")
            }

            for stem, image_entry in sorted(image_entries.items()):
                out_name = f"task{task_id}_{stem}{Path(image_entry).suffix.lower()}"
                (images_dir / out_name).write_bytes(archive.read(image_entry))

                label_entry = label_entries.get(stem)
                if label_entry is not None:
                    (labels_dir / f"task{task_id}_{stem}.txt").write_bytes(archive.read(label_entry))

                split_files.append(f"./images/{out_name}")

    (output_path / "train.txt").write_text("\n".join(train_files) + "\n")
    (output_path / "val.txt").write_text("\n".join(val_files) + "\n")

    data_yaml = {
        "path": str(output_path.resolve()),
        "train": "train.txt",
        "val": "val.txt",
        "nc": 1,
        "names": ["vehicle"],
    }
    data_yaml_path = output_path / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml, f)

    return str(data_yaml_path)

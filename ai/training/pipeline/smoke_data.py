from __future__ import annotations
import random
from pathlib import Path
import yaml
from PIL import Image, ImageDraw


def generate_plate_smoke_dataset(output_dir: str, num_images: int = 8, img_size: int = 320, seed: int = 0) -> str:
    rng = random.Random(seed)
    output_path = Path(output_dir)
    images_dir = output_path / "images"
    labels_dir = output_path / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    num_val = max(1, num_images // 4)
    filenames = [f"plate_{i:03d}" for i in range(num_images)]

    for name in filenames:
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        image = Image.new("RGB", (img_size, img_size), color=color)

        box_w = rng.randint(img_size // 6, img_size // 3)
        box_h = rng.randint(img_size // 10, img_size // 5)
        x0 = rng.randint(0, img_size - box_w)
        y0 = rng.randint(0, img_size - box_h)
        ImageDraw.Draw(image).rectangle([x0, y0, x0 + box_w, y0 + box_h], outline=(0, 0, 0))

        cx = (x0 + box_w / 2) / img_size
        cy = (y0 + box_h / 2) / img_size
        w = box_w / img_size
        h = box_h / img_size

        # corner order: top-left, top-right, bottom-right, bottom-left
        left, right = x0 / img_size, (x0 + box_w) / img_size
        top, bottom = y0 / img_size, (y0 + box_h) / img_size
        keypoints = [
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        ]
        kpt_str = " ".join(f"{x:.6f} {y:.6f}" for x, y in keypoints)

        image.save(images_dir / f"{name}.jpg")
        (labels_dir / f"{name}.txt").write_text(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f} {kpt_str}\n")

    train_files = filenames[:-num_val]
    val_files = filenames[-num_val:]
    (output_path / "train.txt").write_text("\n".join(f"./images/{name}.jpg" for name in train_files) + "\n")
    (output_path / "val.txt").write_text("\n".join(f"./images/{name}.jpg" for name in val_files) + "\n")

    data_yaml = {
        "path": str(output_path.resolve()),
        "train": "train.txt",
        "val": "val.txt",
        "nc": 1,
        "names": ["plate"],
        "kpt_shape": [4, 2],
    }
    data_yaml_path = output_path / "data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data_yaml, f)

    return str(data_yaml_path)

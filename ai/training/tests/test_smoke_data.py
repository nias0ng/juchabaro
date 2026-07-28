import sys

import pytest
import yaml
from pipeline.smoke_data import generate_plate_smoke_dataset


def test_generate_plate_smoke_dataset_creates_expected_files(tmp_path):
    output_dir = tmp_path / "plate"

    data_yaml_path = generate_plate_smoke_dataset(str(output_dir), num_images=8, seed=0)

    images = sorted((output_dir / "images").glob("*.jpg"))
    labels = sorted((output_dir / "labels").glob("*.txt"))
    assert len(images) == 8
    assert len(labels) == 8

    with open(data_yaml_path) as f:
        data_yaml = yaml.safe_load(f)
    assert data_yaml["nc"] == 1
    assert data_yaml["names"] == ["plate"]
    assert data_yaml["kpt_shape"] == [4, 2]


def test_generate_plate_smoke_dataset_label_format_is_valid_yolo_pose(tmp_path):
    output_dir = tmp_path / "plate"

    generate_plate_smoke_dataset(str(output_dir), num_images=4, seed=1)

    label_file = output_dir / "labels" / "plate_000.txt"
    parts = label_file.read_text().strip().split()

    # class + bbox(cx,cy,w,h) + 4 corner keypoints(x,y) = 1 + 4 + 8
    assert len(parts) == 13
    assert parts[0] == "0"
    for value in parts[1:]:
        assert 0.0 <= float(value) <= 1.0


def test_generate_plate_smoke_dataset_keypoints_match_bbox_corners(tmp_path):
    output_dir = tmp_path / "plate"

    generate_plate_smoke_dataset(str(output_dir), num_images=4, seed=1)

    label_file = output_dir / "labels" / "plate_000.txt"
    cx, cy, w, h, x1, y1, x2, y2, x3, y3, x4, y4 = (
        float(v) for v in label_file.read_text().strip().split()[1:]
    )

    left, right = cx - w / 2, cx + w / 2
    top, bottom = cy - h / 2, cy + h / 2

    # corner order: top-left, top-right, bottom-right, bottom-left
    assert (x1, y1) == pytest.approx((left, top), abs=1e-4)
    assert (x2, y2) == pytest.approx((right, top), abs=1e-4)
    assert (x3, y3) == pytest.approx((right, bottom), abs=1e-4)
    assert (x4, y4) == pytest.approx((left, bottom), abs=1e-4)


def test_main_generates_dataset_via_cli(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "plate_cli"
    monkeypatch.setattr(
        sys,
        "argv",
        ["make_plate_smoke_dataset.py", "--output", str(output_dir), "--num-images", "4"],
    )

    from make_plate_smoke_dataset import main

    main()

    captured = capsys.readouterr()
    assert str(output_dir) in captured.out
    assert (output_dir / "data.yaml").exists()
    assert len(list((output_dir / "images").glob("*.jpg"))) == 4

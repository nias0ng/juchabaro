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


def test_generate_plate_smoke_dataset_label_format_is_valid_yolo(tmp_path):
    output_dir = tmp_path / "plate"

    generate_plate_smoke_dataset(str(output_dir), num_images=4, seed=1)

    label_file = output_dir / "labels" / "plate_000.txt"
    parts = label_file.read_text().strip().split()

    assert len(parts) == 5
    assert parts[0] == "0"
    for value in parts[1:]:
        assert 0.0 <= float(value) <= 1.0

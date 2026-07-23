from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.smoke_data import generate_plate_smoke_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic plate-detection smoke test dataset")
    parser.add_argument("--output", default="data/samples/plate")
    parser.add_argument("--num-images", type=int, default=8)
    parser.add_argument("--img-size", type=int, default=320)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    data_yaml_path = generate_plate_smoke_dataset(
        output_dir=args.output,
        num_images=args.num_images,
        img_size=args.img_size,
        seed=args.seed,
    )
    print(data_yaml_path)


if __name__ == "__main__":
    main()

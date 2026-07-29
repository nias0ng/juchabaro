from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.vehicle_dataset import build_vehicle_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge CVAT vehicle-detection task exports into one train/val dataset")
    parser.add_argument("--raw-dir", default="data/raw/vehicle")
    parser.add_argument("--output", default="data/processed/vehicle")
    parser.add_argument("--val-tasks", default="8", help="Comma-separated CVAT task ids to use as the val split")
    args = parser.parse_args()

    val_tasks = [int(t) for t in args.val_tasks.split(",") if t]
    data_yaml_path = build_vehicle_dataset(
        raw_dir=args.raw_dir,
        output_dir=args.output,
        val_tasks=val_tasks,
    )
    print(data_yaml_path)


if __name__ == "__main__":
    main()

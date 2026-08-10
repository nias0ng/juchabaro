from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wandb
from ultralytics import YOLO

from pipeline.config import load_config
from pipeline.versioning import generate_model_version, get_commit_hash
from pipeline.metadata import write_model_meta


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a YOLO detection model")
    parser.add_argument("--config", required=True)
    parser.add_argument("--base-model", default=None)
    parser.add_argument("--batch", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--version", default=None)
    return parser


def run_training(
    config_path: str,
    base_model: str | None = None,
    batch: int | None = None,
    epochs: int | None = None,
    version: str | None = None,
) -> dict:
    config = load_config(config_path, overrides={"base_model": base_model, "batch": batch, "epochs": epochs})
    model_version = version or generate_model_version(config["model_name"], config["base_model"])

    wandb.init(project=config["project"], name=model_version, config=config)

    try:
        model = YOLO(config["base_model"])
        results = model.train(
            data=config["data"],
            epochs=config["epochs"],
            imgsz=config["imgsz"],
            batch=config["batch"],
            device=config["device"],
            project="runs/train",
            name=model_version,
        )

        results_dict = getattr(results, "results_dict", {})
        metrics = {
            "mAP50": results_dict.get("metrics/mAP50(B)", 0.0),
            "mAP50-95": results_dict.get("metrics/mAP50-95(B)", 0.0),
        }
        if "metrics/mAP50(P)" in results_dict or "metrics/mAP50-95(P)" in results_dict:
            metrics["pose_mAP50"] = results_dict.get("metrics/mAP50(P)", 0.0)
            metrics["pose_mAP50-95"] = results_dict.get("metrics/mAP50-95(P)", 0.0)

        weights_dir = Path(results.save_dir) / "weights"
        meta_path = write_model_meta(
            weights_dir=str(weights_dir),
            model_name=config["model_name"],
            model_version=model_version,
            base_model=config["base_model"],
            dataset=config["data"],
            hyperparams={"epochs": config["epochs"], "imgsz": config["imgsz"], "batch": config["batch"]},
            metrics=metrics,
            commit_hash=get_commit_hash(),
        )

        return {
            "model_version": model_version,
            "best_weights": str(weights_dir / "best.pt"),
            "meta_path": meta_path,
        }
    finally:
        wandb.finish()


def main() -> None:
    args = build_arg_parser().parse_args()
    result = run_training(
        config_path=args.config,
        base_model=args.base_model,
        batch=args.batch,
        epochs=args.epochs,
        version=args.version,
    )
    print(result["model_version"])
    print(result["best_weights"])


if __name__ == "__main__":
    main()

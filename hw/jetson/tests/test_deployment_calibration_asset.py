"""운영 calibration 복사본과 좌표계 snapshot의 연결을 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from src.camera.calibration_utils import load_calibration
from src.camera.frame_source import calibration_fingerprint


JETSON_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENT_CALIBRATION = JETSON_ROOT / "config" / "camera_calibration.json"
AI_CALIBRATION = REPOSITORY_ROOT / "ai" / "tracking" / "camera_calibration.json"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_deployment_calibration_matches_reference_snapshots() -> None:
    """운영 파일의 지문이 full-frame zone·egress snapshot과 같아야 한다."""

    load_calibration(str(DEPLOYMENT_CALIBRATION))
    reference = calibration_fingerprint(
        DEPLOYMENT_CALIBRATION,
        balance=0.5,
    )["calibrationSha256"]

    assert reference == "a26d3085c3d4fc4f"
    assert (
        _read_json(JETSON_ROOT / "config" / "zone_definition.json")[
            "calibrationReference"
        ]
        == reference
    )
    assert (
        _read_json(JETSON_ROOT / "config" / "egress_aisle.json")[
            "calibrationReference"
        ]
        == reference
    )


def test_deployment_and_ai_calibrations_have_same_values() -> None:
    """운영 복사본과 기존 Viewer·live용 파일의 수치 drift를 막는다."""

    assert _read_json(DEPLOYMENT_CALIBRATION) == _read_json(AI_CALIBRATION)

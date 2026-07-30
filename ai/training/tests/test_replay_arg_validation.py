"""리플레이 진입 스크립트(`replay_pilot_video.py`)의 인자 검증 회귀 테스트.

`--calibration` 없이도 zones 파일과 지문이 서로 일치해버리면(둘 다 remap: false),
왜곡이 남은 원본 프레임으로 오버레이와 "검증됨" 판정을 만들어낼 수 있다 — 모델은
remap 보정된 프레임으로 학습됐는데도. `validate_args`가 이 실행 자체를 막는지
서브프로세스 없이 직접 호출해서 고정한다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from jetson_vehicle_tracking_baseline import BaselineError
from replay_pilot_video import validate_args


def make_args(*, calibration=None, remap_balance: float = 0.5) -> argparse.Namespace:
    return argparse.Namespace(calibration=calibration, remap_balance=remap_balance)


def test_replay_rejects_missing_calibration(tmp_path: Path) -> None:
    with pytest.raises(BaselineError):
        validate_args(make_args(calibration=None))


def test_replay_rejects_remap_balance_out_of_range(tmp_path: Path) -> None:
    calibration_path = tmp_path / "camera_calibration.json"
    calibration_path.write_text("{}", encoding="utf-8")
    with pytest.raises(BaselineError):
        validate_args(make_args(calibration=calibration_path, remap_balance=1.5))


def test_replay_rejects_nonexistent_calibration_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.json"
    with pytest.raises(BaselineError):
        validate_args(make_args(calibration=missing_path))

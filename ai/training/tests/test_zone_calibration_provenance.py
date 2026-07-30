"""zone 폴리곤 좌표계와 remap 보정 설정의 일치 검증 회귀 테스트.

remap은 픽셀을 최대 130px 옮기므로, 보정 없이 찍은 zone 폴리곤을 --calibration과 함께
쓰면 아무 에러 없이 위반 판정이 어긋난다. 그 불일치를 잡아내는지 확인한다.
"""

import argparse
import json

import pytest
from jetson_vehicle_tracking_baseline import (
    BaselineError,
    calibration_fingerprint,
    verify_zone_calibration,
)


def make_args(zones_file, calibration=None, remap_balance=0.5):
    return argparse.Namespace(
        zones_file=zones_file, calibration=calibration, remap_balance=remap_balance
    )


def write_calibration_file(tmp_path, name="camera_calibration.json", fx=260.0):
    path = tmp_path / name
    path.write_text(
        json.dumps({"K": [[fx, 0, 205], [0, fx, 148], [0, 0, 1]], "D": [0, 0, 0, 0], "image_size": [400, 300]}),
        encoding="utf-8",
    )
    return path


def write_zones(tmp_path, calibration_block=None):
    payload = {
        "zones": [
            {"zone_id": "GEN-01", "zone_type": "GENERAL", "polygon": [[0, 0], [0.2, 0], [0.2, 0.2], [0, 0.2]]}
        ]
    }
    if calibration_block is not None:
        payload["calibration"] = calibration_block
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_fingerprint_marks_absence_of_remap():
    assert calibration_fingerprint(None, 0.5) == {"remap": False}


def test_fingerprint_changes_with_calibration_contents(tmp_path):
    a = write_calibration_file(tmp_path, "a.json", fx=260.0)
    b = write_calibration_file(tmp_path, "b.json", fx=999.0)

    assert calibration_fingerprint(a, 0.5) != calibration_fingerprint(b, 0.5)


def test_fingerprint_changes_with_balance(tmp_path):
    path = write_calibration_file(tmp_path)

    assert calibration_fingerprint(path, 0.5) != calibration_fingerprint(path, 1.0)


def test_fingerprint_is_stable_for_same_inputs(tmp_path):
    path = write_calibration_file(tmp_path)

    assert calibration_fingerprint(path, 0.5) == calibration_fingerprint(path, 0.5)


def test_accepts_zones_captured_with_matching_calibration(tmp_path):
    calibration = write_calibration_file(tmp_path)
    zones = write_zones(tmp_path, calibration_fingerprint(calibration, 0.5))

    verify_zone_calibration(make_args(zones, calibration, 0.5))  # 예외 없이 통과해야 한다


def test_rejects_zones_captured_without_remap(tmp_path):
    """가장 위험한 시나리오 — 보정 도입 전에 만든 zones 파일을 그대로 쓰는 경우."""
    calibration = write_calibration_file(tmp_path)
    zones = write_zones(tmp_path, {"remap": False})

    with pytest.raises(BaselineError):
        verify_zone_calibration(make_args(zones, calibration, 0.5))


def test_rejects_zones_captured_with_different_balance(tmp_path):
    calibration = write_calibration_file(tmp_path)
    zones = write_zones(tmp_path, calibration_fingerprint(calibration, 1.0))

    with pytest.raises(BaselineError):
        verify_zone_calibration(make_args(zones, calibration, 0.5))


def test_rejects_zones_captured_with_different_calibration_file(tmp_path):
    old = write_calibration_file(tmp_path, "old.json", fx=260.0)
    new = write_calibration_file(tmp_path, "new.json", fx=999.0)
    zones = write_zones(tmp_path, calibration_fingerprint(old, 0.5))

    with pytest.raises(BaselineError):
        verify_zone_calibration(make_args(zones, new, 0.5))


def test_warns_but_passes_when_zones_have_no_fingerprint(tmp_path, caplog):
    """기존 zones 파일과의 호환 — 검증은 못 하지만 실행을 막지는 않는다."""
    calibration = write_calibration_file(tmp_path)
    zones = write_zones(tmp_path, calibration_block=None)

    verify_zone_calibration(make_args(zones, calibration, 0.5))

    assert any("calibration 지문이 없어" in record.message for record in caplog.records)

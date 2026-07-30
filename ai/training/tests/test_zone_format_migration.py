"""zones 파일 포맷 이관(구역 계약 스펙 §9) 회귀 테스트.

지문을 JSON·MySQL DECIMAL을 왕복시키면 dict 통째 비교가 두 군데서 깨진다:
remap=False일 때의 키 개수 차이, 그리고 0.5 vs 0.500000. 그 두 함정을 고정한다.
"""

import json

import pytest
from jetson_vehicle_tracking_baseline import (
    BaselineError,
    calibration_fingerprint,
    normalize_fingerprint,
)


def write_calibration_file(tmp_path, name="camera_calibration.json", fx=260.0):
    path = tmp_path / name
    path.write_text(
        json.dumps({"K": [[fx, 0, 205], [0, fx, 148], [0, 0, 1]], "D": [0, 0, 0, 0], "image_size": [400, 300]}),
        encoding="utf-8",
    )
    return path


def test_fingerprint_uses_wire_format_keys(tmp_path):
    """서버 응답·POST 바디·사이드카가 모두 camelCase를 쓰므로 지문도 같아야 한다."""
    path = write_calibration_file(tmp_path)

    fingerprint = calibration_fingerprint(path, 0.5)

    assert set(fingerprint) == {"remap", "calibrationSha256", "balance"}
    assert fingerprint["remap"] is True
    assert len(fingerprint["calibrationSha256"]) == 16


def test_normalize_treats_absent_and_null_remap_fields_as_equal():
    """calibration_fingerprint는 remap=False면 한 키만 만들지만 서버는 null로 채워 보낸다."""
    local = {"remap": False}
    from_server = {"remap": False, "calibrationSha256": None, "balance": None}

    assert normalize_fingerprint(local) == normalize_fingerprint(from_server)


def test_normalize_treats_decimal_padded_balance_as_equal():
    """MySQL DECIMAL(8,6)을 거치면 0.5가 0.500000으로 돌아온다."""
    a = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 0.5}
    b = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 0.500000}

    assert normalize_fingerprint(a) == normalize_fingerprint(b)


def test_normalize_is_case_insensitive_for_sha():
    a = {"remap": True, "calibrationSha256": "A1B2C3D4E5F60718", "balance": 0.5}
    b = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 0.5}

    assert normalize_fingerprint(a) == normalize_fingerprint(b)


def test_normalize_keeps_sha_mismatch_distinct():
    a = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 0.5}
    b = {"remap": True, "calibrationSha256": "ffffffffffffffff", "balance": 0.5}

    assert normalize_fingerprint(a) != normalize_fingerprint(b)


def test_normalize_keeps_balance_mismatch_distinct():
    a = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 0.5}
    b = {"remap": True, "calibrationSha256": "a1b2c3d4e5f60718", "balance": 1.0}

    assert normalize_fingerprint(a) != normalize_fingerprint(b)


def test_normalize_rejects_remap_true_without_sha():
    """반쪽짜리 지문은 조용히 통과시키면 안 된다."""
    with pytest.raises(BaselineError):
        normalize_fingerprint({"remap": True, "balance": 0.5})

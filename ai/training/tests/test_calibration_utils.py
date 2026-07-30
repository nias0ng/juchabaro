import json

import numpy as np
import pytest
from calibration_utils import CalibrationError, load_calibration, scale_K


def _write(tmp_path, **overrides):
    data = {
        "K": [[80.0, 0.0, 50.0], [0.0, 80.0, 40.0], [0.0, 0.0, 1.0]],
        "D": [0.01, 0.0, 0.0, 0.0],
        "image_size": [100, 80],
    }
    data.update(overrides)
    path = tmp_path / "camera_calibration.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_calibration_parses_k_d_and_size(tmp_path):
    K, D, image_size = load_calibration(str(_write(tmp_path)))

    assert K.shape == (3, 3)
    assert D.shape == (4, 1)
    assert image_size == (100, 80)
    assert K[0, 0] == pytest.approx(80.0)


def test_load_calibration_rejects_missing_file(tmp_path):
    with pytest.raises(CalibrationError):
        load_calibration(str(tmp_path / "nope.json"))


def test_load_calibration_rejects_malformed_json(tmp_path):
    path = tmp_path / "camera_calibration.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CalibrationError):
        load_calibration(str(path))


@pytest.mark.parametrize("missing", ["K", "D", "image_size"])
def test_load_calibration_rejects_missing_keys(tmp_path, missing):
    data = json.loads(_write(tmp_path).read_text(encoding="utf-8"))
    del data[missing]
    path = tmp_path / "camera_calibration.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CalibrationError):
        load_calibration(str(path))


def test_load_calibration_rejects_pinhole_five_coefficient_d(tmp_path):
    """cv2.fisheye는 계수가 정확히 4개다. 핀홀 모델의 5개짜리 D를 조용히 잘라 쓰면
    왜곡 보정이 틀어지므로 명시적으로 거부해야 한다."""
    path = _write(tmp_path, D=[0.01, 0.0, 0.0, 0.0, 0.0])

    with pytest.raises(CalibrationError):
        load_calibration(str(path))


def test_scale_K_scales_focal_length_and_principal_point(tmp_path):
    K, _, _ = load_calibration(str(_write(tmp_path)))

    scaled = scale_K(K, (100, 80), (200, 160))

    # 정확히 2배 리샘플이므로 fx, fy, cx, cy 모두 2배여야 한다.
    assert scaled[0, 0] == pytest.approx(160.0)
    assert scaled[1, 1] == pytest.approx(160.0)
    assert scaled[0, 2] == pytest.approx(100.0)
    assert scaled[1, 2] == pytest.approx(80.0)
    assert scaled[2, 2] == pytest.approx(1.0)


def test_scale_K_is_noop_for_same_size_but_returns_a_copy(tmp_path):
    K, _, _ = load_calibration(str(_write(tmp_path)))

    scaled = scale_K(K, (100, 80), (100, 80))

    assert np.array_equal(scaled, K)
    # 두 호출자가 같은 배열을 공유하면 한쪽의 in-place 수정이 다른 쪽을 오염시킨다.
    assert scaled is not K
    scaled[0, 0] = 999.0
    assert K[0, 0] == pytest.approx(80.0)


def test_default_remap_balance_matches_between_training_and_inference():
    """balance가 다르면 같은 K/D로도 다른 좌표계가 나온다. 학습 데이터를 만드는
    extract_pilot_frames.py와 추론 쪽 baseline의 기본값이 갈라지면 조용히 어긋나므로,
    두 상수가 항상 같은지 고정한다."""
    import calibration_utils
    import extract_pilot_frames
    import jetson_vehicle_tracking_baseline

    assert (
        extract_pilot_frames.DEFAULT_REMAP_BALANCE
        == jetson_vehicle_tracking_baseline.DEFAULT_REMAP_BALANCE
        == calibration_utils.DEFAULT_REMAP_BALANCE
    )


def test_scale_K_rejects_aspect_ratio_change(tmp_path):
    """16:9로 캘리브레이션한 값을 4:3 프레임에 쓰면 cx/cy 스케일링이 틀린다
    (센서 크롭인 경우 화각 자체가 달라짐). 조용히 틀리는 대신 예외를 던져야 한다."""
    K, _, _ = load_calibration(str(_write(tmp_path, image_size=[1920, 1080])))

    with pytest.raises(CalibrationError):
        scale_K(K, (1920, 1080), (640, 480))

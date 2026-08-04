"""recrop_zone_definition의 폴리곤 좌표 재정규화 골든 파일 테스트."""

import pytest
from scripts.recrop_zone_definition import RecropError, recrop_payload

SAMPLE_PAYLOAD = {
    "zoneDefinitionVersion": 3,
    "calibrationReference": "a5d846f6bfc40eb3",
    "zones": [
        {
            "zoneId": 1,
            "zoneType": "EV_CHARGING",
            "polygon": [[0.230, 0.435], [0.372, 0.428], [0.379, 0.594], [0.234, 0.602]],
            "allowedDurationSeconds": 7200,
            "chargerClass": "FAST",
            "egressZoneIds": [7],
        },
    ],
}


def test_recomputes_polygon_x_for_new_width():
    result = recrop_payload(SAMPLE_PAYLOAD, old_width=1920, crop_left_px=150, crop_right_px=0)

    new_width = 1920 - 150
    expected_x = (0.230 * 1920 - 150) / new_width
    assert result["zones"][0]["polygon"][0][0] == pytest.approx(expected_x, abs=1e-6)
    # y좌표는 그대로 유지된다.
    assert result["zones"][0]["polygon"][0][1] == 0.435


def test_bumps_version_and_keeps_calibration_reference():
    result = recrop_payload(SAMPLE_PAYLOAD, old_width=1920, crop_left_px=150, crop_right_px=0)

    assert result["zoneDefinitionVersion"] == 4
    assert result["calibrationReference"] == "a5d846f6bfc40eb3"


def test_preserves_non_polygon_zone_fields():
    result = recrop_payload(SAMPLE_PAYLOAD, old_width=1920, crop_left_px=150, crop_right_px=0)

    zone = result["zones"][0]
    assert zone["zoneId"] == 1
    assert zone["zoneType"] == "EV_CHARGING"
    assert zone["allowedDurationSeconds"] == 7200
    assert zone["chargerClass"] == "FAST"
    assert zone["egressZoneIds"] == [7]


def test_raises_when_cropped_coordinate_falls_outside_unit_range():
    # crop_left_px가 너무 커서 zone 1의 왼쪽 꼭짓점(x=0.230)이 음수로 밀려난다.
    with pytest.raises(RecropError, match=r"\[0, 1\]"):
        recrop_payload(SAMPLE_PAYLOAD, old_width=1920, crop_left_px=500, crop_right_px=0)


def test_raises_when_crop_amounts_exceed_frame_width():
    with pytest.raises(RecropError, match="프레임 폭"):
        recrop_payload(SAMPLE_PAYLOAD, old_width=1920, crop_left_px=1000, crop_right_px=1000)

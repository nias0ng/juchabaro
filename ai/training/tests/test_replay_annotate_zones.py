"""ZoneAnnotator 계약 테스트.

cv2 창·마우스 콜백은 자동 테스트가 불가능하지만, "클릭 좌표 → 정규화 → 검증 →
JSON"은 순수 로직이라 전부 고정할 수 있다. 산출물이 ZoneRegistry로 다시 읽히고
verify_zone_calibration을 통과하는지가 이 도구의 최종 계약이다.
"""

import argparse
import json

import pytest
from jetson_vehicle_tracking_baseline import (
    BaselineError,
    ZoneRegistry,
    ZoneType,
    calibration_fingerprint,
    verify_zone_calibration,
)
from replay.zone_annotator import ZoneAnnotator

SQUARE = [(0, 0), (192, 0), (192, 108), (0, 108)]  # 1920x1080에서 10% 정사각형


def write_calibration_file(tmp_path, fx=260.0):
    path = tmp_path / "camera_calibration.json"
    path.write_text(
        json.dumps({"K": [[fx, 0, 205], [0, fx, 148], [0, 0, 1]], "D": [0, 0, 0, 0], "image_size": [400, 300]}),
        encoding="utf-8",
    )
    return path


def make_annotator(calibration_path, balance=0.5):
    return ZoneAnnotator(
        frame_width=1920,
        frame_height=1080,
        camera_code="PILOT-VIDEO",
        calibration=calibration_fingerprint(calibration_path, balance),
    )


def click_zone(annotator, points, zone_type, zone_number, allowed_minutes=None):
    for px, py in points:
        annotator.add_point(px, py)
    annotator.commit(zone_type=zone_type, zone_number=zone_number, allowed_minutes=allowed_minutes)


def test_points_are_normalized_by_frame_size(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")

    polygon = annotator.payload()["zones"][0]["polygon"]

    assert polygon == [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1]]


def test_zone_ids_are_assigned_from_one_and_marked_local(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")
    click_zone(annotator, SQUARE, ZoneType.AISLE, "AISLE-01")

    payload = annotator.payload()

    assert payload["source"] == "local"
    assert [z["zoneId"] for z in payload["zones"]] == [1, 2]


def test_payload_round_trips_through_zone_registry(tmp_path):
    calibration = write_calibration_file(tmp_path)
    annotator = make_annotator(calibration)
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(annotator.payload()), encoding="utf-8")

    registry = ZoneRegistry.from_file(path)

    assert registry.get(1).zone_number == "GEN-01"
    assert registry.get(1).zone_type == ZoneType.GENERAL


def test_payload_passes_calibration_verification(tmp_path):
    calibration = write_calibration_file(tmp_path)
    annotator = make_annotator(calibration, balance=0.5)
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(annotator.payload()), encoding="utf-8")

    verify_zone_calibration(
        argparse.Namespace(zones_file=path, calibration=calibration, remap_balance=0.5)
    )  # 예외 없이 통과해야 한다


def test_payload_rejected_when_verified_with_different_balance(tmp_path):
    """지문이 실제로 작동하는지 — 다른 balance로 검증하면 막혀야 한다."""
    calibration = write_calibration_file(tmp_path)
    annotator = make_annotator(calibration, balance=0.5)
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(annotator.payload()), encoding="utf-8")

    with pytest.raises(BaselineError):
        verify_zone_calibration(
            argparse.Namespace(zones_file=path, calibration=calibration, remap_balance=1.0)
        )


def test_commit_rejects_polygon_with_two_points(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    annotator.add_point(0, 0)
    annotator.add_point(100, 0)

    with pytest.raises(BaselineError):
        annotator.commit(zone_type=ZoneType.GENERAL, zone_number="GEN-01", allowed_minutes=None)


def test_commit_rejects_duplicate_zone_number(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")

    with pytest.raises(BaselineError):
        click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")


def test_commit_requires_allowed_minutes_for_ev_zones(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))

    with pytest.raises(BaselineError):
        click_zone(annotator, SQUARE, ZoneType.EV_FAST, "EV-01", allowed_minutes=None)


def test_commit_rejects_allowed_minutes_for_aisle(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))

    with pytest.raises(BaselineError):
        click_zone(annotator, SQUARE, ZoneType.AISLE, "AISLE-01", allowed_minutes=120)


def test_ev_zone_keeps_allowed_minutes_in_payload(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    click_zone(annotator, SQUARE, ZoneType.EV_FAST, "EV-01", allowed_minutes=120)

    assert annotator.payload()["zones"][0]["allowedMinutes"] == 120

def test_payload_rejects_empty_zone_list(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))

    with pytest.raises(BaselineError):
        annotator.payload()


def test_undo_point_removes_last_pending_point(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    annotator.add_point(0, 0)
    annotator.add_point(100, 0)
    annotator.undo_point()

    assert annotator.pending_points == [(0, 0)]


def test_undo_zone_removes_last_committed_zone_and_frees_its_number(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")
    annotator.undo_zone()

    assert annotator.zones == []
    click_zone(annotator, SQUARE, ZoneType.GENERAL, "GEN-01")  # 번호를 다시 쓸 수 있어야 한다
    assert annotator.payload()["zones"][0]["zoneId"] == 1


def test_add_point_rejects_coordinate_outside_frame(tmp_path):
    annotator = make_annotator(write_calibration_file(tmp_path))

    with pytest.raises(BaselineError):
        annotator.add_point(1920, 0)

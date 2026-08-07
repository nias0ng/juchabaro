"""Monitoring runtime Settings의 필수값과 장치 설정 제약을 검증한다."""

import pytest
from pydantic import ValidationError

from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.config.settings import Settings


def test_monitoring_runtime_fields_keep_only_established_defaults() -> None:
    fields = Settings.model_fields

    for name in (
        "camera_id",
        "camera_index",
        "calibration_path",
        "vehicle_model_path",
        "vehicle_model_manifest_path",
        "vehicle_tracking_confidence",
        "exit_reentry_confirmation_seconds",
        "reidentification_max_gap_seconds",
        "reidentification_min_score",
        "reidentification_ambiguity_margin",
        "incident_disabled_zone_unauthorized_confirm_seconds",
        "incident_disabled_zone_unauthorized_clear_seconds",
        "incident_ev_zone_unauthorized_confirm_seconds",
        "incident_ev_zone_unauthorized_clear_seconds",
        "incident_ev_overstay_confirm_seconds",
        "incident_ev_overstay_clear_seconds",
        "incident_bad_parking_confirm_seconds",
        "incident_bad_parking_clear_seconds",
        "incident_out_of_zone_confirm_seconds",
        "incident_out_of_zone_clear_seconds",
        "incident_aisle_block_confirm_seconds",
        "incident_aisle_block_clear_seconds",
        "incident_double_parking_confirm_seconds",
        "incident_double_parking_clear_seconds",
        "zone_presence_min_overlap_ratio",
        "assignment_min_overlap_ratio",
        "assignment_ambiguous_margin",
        "bad_parking_min_primary_overlap_ratio",
        "bad_parking_min_secondary_overlap_ratio",
        "out_of_zone_min_spot_overlap_ratio",
        "blocking_relation_confirm_seconds",
        "blocking_relation_clear_seconds",
        "blocking_min_subject_overlap_ratio",
        "blocking_min_egress_coverage_ratio",
    ):
        assert fields[name].is_required()

    assert fields["camera_width"].default == 0
    assert fields["camera_height"].default == 0
    assert fields["camera_fourcc"].default is None
    assert fields["camera_fps"].default == 0.0
    assert fields["remap_balance"].default == DEFAULT_REMAP_BALANCE
    assert fields["vehicle_tracker_config"].default == "bytetrack.yaml"
    assert fields["entry_zone_min_overlap_ratio"].default == 0.40
    assert fields["incident_confirm_seconds"].default == 0.0
    assert fields["incident_clear_seconds"].default == 0.0


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("camera_id", "   "),
        ("camera_index", -1),
        ("camera_width", -1),
        ("camera_height", -1),
        ("camera_fourcc", ""),
        ("camera_fourcc", "YUYV1"),
        ("camera_fourcc", "한글AB"),
        ("camera_fps", -1),
        ("camera_fps", float("nan")),
        ("camera_fps", float("inf")),
        ("calibration_path", ""),
        ("calibration_path", "   "),
        ("remap_balance", -0.1),
        ("remap_balance", 1.1),
        ("remap_balance", float("nan")),
        ("remap_balance", float("inf")),
        ("vehicle_model_path", ""),
        ("vehicle_model_path", "   "),
        ("vehicle_model_manifest_path", ""),
        ("vehicle_model_manifest_path", "   "),
        ("vehicle_tracker_config", " "),
        ("vehicle_tracking_confidence", -0.1),
        ("vehicle_tracking_confidence", 1.1),
        ("vehicle_tracking_confidence", float("nan")),
        ("vehicle_tracking_confidence", float("inf")),
        ("exit_reentry_confirmation_seconds", 0.0),
        ("exit_reentry_confirmation_seconds", -0.1),
        ("exit_reentry_confirmation_seconds", float("nan")),
        ("exit_reentry_confirmation_seconds", float("inf")),
    ),
)
def test_settings_reject_invalid_device_configuration(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **{field_name: invalid_value})

    error_fields = {
        error["loc"][0]
        for error in exc_info.value.errors()
    }
    assert error_fields == {field_name}


def test_camera_fourcc_is_normalized() -> None:
    settings = Settings(_env_file=None, camera_fourcc=" mjpg ")

    assert settings.camera_fourcc == "MJPG"


@pytest.mark.parametrize(
    "field_name",
    (
        "incident_disabled_zone_unauthorized_confirm_seconds",
        "incident_disabled_zone_unauthorized_clear_seconds",
        "incident_ev_zone_unauthorized_confirm_seconds",
        "incident_ev_zone_unauthorized_clear_seconds",
        "incident_ev_overstay_confirm_seconds",
        "incident_ev_overstay_clear_seconds",
        "incident_bad_parking_confirm_seconds",
        "incident_bad_parking_clear_seconds",
        "incident_out_of_zone_confirm_seconds",
        "incident_out_of_zone_clear_seconds",
        "incident_aisle_block_confirm_seconds",
        "incident_aisle_block_clear_seconds",
        "incident_double_parking_confirm_seconds",
        "incident_double_parking_clear_seconds",
    ),
)
def test_rule_specific_incident_timing_rejects_negative_values(
    field_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **{field_name: -0.1})

    error_fields = {
        error["loc"][0]
        for error in exc_info.value.errors()
    }
    assert error_fields == {field_name}

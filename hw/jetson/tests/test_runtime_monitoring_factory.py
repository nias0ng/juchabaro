"""운영 camera·tracking Monitoring factory의 composition 계약을 검증한다."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from src.application.monitoring_factory import MonitoringPolicy
from src.camera.frame_source import calibration_fingerprint
from src.config.settings import Settings
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.parking.models import (
    IncidentRuleTiming,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.rules.bad_parking import (
    AISLE_BLOCK,
    BAD_PARKING,
    OUT_OF_ZONE,
)
from src.parking.rules.double_parking import DOUBLE_PARKING
from src.parking.rules.ev_overstay import EV_OVERSTAY
from src.parking.rules.restricted_zone import (
    DISABLED_ZONE_UNAUTHORIZED,
    EV_ZONE_UNAUTHORIZED,
)
from src.parking.zone_registry import ZoneRegistry


def _write_calibration(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "K": [
                    [260.0, 0.0, 200.0],
                    [0.0, 260.0, 150.0],
                    [0.0, 0.0, 1.0],
                ],
                "D": [0.0, 0.0, 0.0, 0.0],
                "image_size": [400, 300],
            }
        ),
        encoding="utf-8",
    )
    return path


def _settings(
    tmp_path: Path,
    *,
    calibration_path: Path,
    model_path: Path,
) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.db",
        evidence_spool_path=tmp_path / "evidence",
        evidence_spool_cap_bytes=8 * 1024 * 1024,
        zone_definition_path=tmp_path / "zones.json",
        egress_aisle_path=tmp_path / "egress.json",
        camera_id="RUNTIME-CAMERA",
        camera_index=2,
        camera_width=1920,
        camera_height=1080,
        calibration_path=calibration_path,
        remap_balance=0.5,
        vehicle_model_path=model_path,
        vehicle_tracker_config="bytetrack.yaml",
        vehicle_tracking_confidence=0.55,
        mask_margin_ratio=0.05,
        zone_entry_confirm_seconds=1.1,
        zone_exit_confirm_seconds=1.2,
        entry_zone_min_overlap_ratio=0.31,
        reidentification_max_gap_seconds=2.0,
        reidentification_min_score=0.41,
        reidentification_ambiguity_margin=0.07,
        incident_confirm_seconds=0.2,
        incident_clear_seconds=0.3,
        incident_disabled_zone_unauthorized_confirm_seconds=0.01,
        incident_disabled_zone_unauthorized_clear_seconds=0.02,
        incident_ev_zone_unauthorized_confirm_seconds=0.03,
        incident_ev_zone_unauthorized_clear_seconds=0.04,
        incident_ev_overstay_confirm_seconds=0.05,
        incident_ev_overstay_clear_seconds=0.06,
        incident_bad_parking_confirm_seconds=0.07,
        incident_bad_parking_clear_seconds=0.08,
        incident_out_of_zone_confirm_seconds=0.09,
        incident_out_of_zone_clear_seconds=0.10,
        incident_aisle_block_confirm_seconds=0.11,
        incident_aisle_block_clear_seconds=0.12,
        incident_double_parking_confirm_seconds=0.13,
        incident_double_parking_clear_seconds=0.14,
        zone_presence_min_overlap_ratio=0.32,
        assignment_min_overlap_ratio=0.52,
        assignment_ambiguous_margin=0.06,
        bad_parking_min_primary_overlap_ratio=0.76,
        bad_parking_min_secondary_overlap_ratio=0.26,
        out_of_zone_min_spot_overlap_ratio=0.51,
        blocking_relation_confirm_seconds=1.5,
        blocking_relation_clear_seconds=1.6,
        blocking_min_subject_overlap_ratio=0.43,
        blocking_min_egress_coverage_ratio=0.44,
        absence_confirmation_seconds=10.0,
        trusted_sample_max_gap_seconds=1.4,
        motion_window_seconds=0.8,
        motion_min_observation_span_seconds=0.21,
        motion_max_sample_gap_seconds=0.4,
        motion_stationary_threshold=0.03,
        motion_moving_threshold=0.11,
        motion_min_samples=4,
        motion_min_trend_consistency=0.61,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=1.3,
    )


def _zones(
    calibration_reference: str,
    *,
    polygon: tuple[tuple[float, float], ...] = (
        (0.2, 0.2),
        (0.8, 0.2),
        (0.5, 0.8),
    ),
) -> ZoneRegistry:
    return ZoneRegistry(
        (
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=ZoneType.AISLE,
                polygon=polygon,
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference=calibration_reference,
            ),
        )
    )


def _context(
    main: Any,
    settings: Settings,
    zones: ZoneRegistry,
) -> tuple[
    Any,
    object,
    Callable[[], sqlite3.Connection],
    object,
]:
    publication_preparer = object()

    def connection_factory() -> sqlite3.Connection:
        raise AssertionError(
            "pipeline construction must not open a database connection"
        )

    evidence_capture_coordinator = object()
    egress_aisles = EgressAisleRegistry.empty(zones)
    context = main.RuntimeContext(
        settings=settings,
        zones=zones,
        egress_aisles=egress_aisles,
        connection_factory=connection_factory,
        publication_preparer=publication_preparer,
        evidence_capture_coordinator=evidence_capture_coordinator,
    )
    return (
        context,
        publication_preparer,
        connection_factory,
        evidence_capture_coordinator,
    )


def _install_composition_spies(
    main: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], object]:
    calls: dict[str, Any] = {}

    def constructor(
        name: str,
    ) -> Callable[..., SimpleNamespace]:
        def construct(**kwargs: Any) -> SimpleNamespace:
            instance = SimpleNamespace(kind=name, **kwargs)
            calls[name] = (kwargs, instance)
            return instance

        return construct

    monkeypatch.setattr(
        main,
        "OpenCvWebcamFrameSource",
        constructor("webcam"),
    )
    monkeypatch.setattr(
        main,
        "RemapFrameSource",
        constructor("remap"),
    )
    monkeypatch.setattr(
        main,
        "UltralyticsVehicleTracker",
        constructor("tracker"),
    )
    monkeypatch.setattr(
        main,
        "SideMaskingDetector",
        constructor("masking"),
    )

    pipeline = object()

    def build_pipeline(**kwargs: Any) -> object:
        calls["build"] = kwargs
        return pipeline

    monkeypatch.setattr(main, "build_monitoring_pipeline", build_pipeline)
    return calls, pipeline


def _block_composition(
    main: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    calls: list[str] = []

    def unexpected(name: str) -> Callable[..., object]:
        def call(*_args: Any, **_kwargs: Any) -> object:
            calls.append(name)
            return object()

        return call

    for name in (
        "OpenCvWebcamFrameSource",
        "RemapFrameSource",
        "UltralyticsVehicleTracker",
        "SideMaskingDetector",
        "build_monitoring_pipeline",
    ):
        monkeypatch.setattr(main, name, unexpected(name))

    return calls


def test_runtime_factory_builds_camera_tracker_and_dependency_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    calibration_path = _write_calibration(tmp_path / "calibration.json")
    model_path = tmp_path / "vehicle.engine"
    model_path.write_bytes(b"test-model")
    settings = _settings(
        tmp_path,
        calibration_path=calibration_path,
        model_path=model_path,
    )
    calibration_reference = calibration_fingerprint(
        calibration_path,
        settings.remap_balance,
    )["calibrationSha256"]
    zones = _zones(calibration_reference)
    (
        context,
        publication_preparer,
        connection_factory,
        evidence_capture_coordinator,
    ) = _context(main, settings, zones)
    calls, expected_pipeline = _install_composition_spies(
        main,
        monkeypatch,
    )

    pipeline = main.build_runtime_monitoring_pipeline(context)

    assert pipeline is expected_pipeline

    webcam_args, webcam = calls["webcam"]
    assert webcam_args == {
        "camera_id": "RUNTIME-CAMERA",
        "camera_index": 2,
        "width": 1920,
        "height": 1080,
    }

    remap_args, remap = calls["remap"]
    assert remap_args == {
        "inner": webcam,
        "calibration_path": str(calibration_path),
        "balance": 0.5,
    }

    tracker_args, tracker = calls["tracker"]
    assert tracker_args == {
        "model_path": str(model_path),
        "tracker_config": "bytetrack.yaml",
        "confidence": 0.55,
    }

    masking_args, masking = calls["masking"]
    assert masking_args["inner"] is tracker
    assert masking_args["left_mask_end_ratio"] == pytest.approx(0.15)
    assert masking_args["right_mask_start_ratio"] == pytest.approx(0.85)

    passed = calls["build"]
    assert set(passed) == {
        "zones",
        "egress_aisles",
        "policy",
        "dependencies",
    }
    assert passed["zones"] is zones
    assert passed["egress_aisles"] is context.egress_aisles
    assert passed["policy"] == main._build_monitoring_policy(settings)
    assert passed["dependencies"].frame_source is remap
    assert passed["dependencies"].detector is masking
    assert passed["dependencies"].camera_id == settings.camera_id
    assert (
        passed["dependencies"].publication_preparer
        is publication_preparer
    )
    assert (
        passed["dependencies"].connection_factory
        is connection_factory
    )
    assert (
        passed["dependencies"].evidence_capture_sink
        is evidence_capture_coordinator
    )


def test_monitoring_policy_maps_all_settings_without_interpretation(
    tmp_path: Path,
) -> None:
    import src.main as main

    settings = _settings(
        tmp_path,
        calibration_path=tmp_path / "calibration.json",
        model_path=tmp_path / "vehicle.engine",
    )

    assert main._build_monitoring_policy(settings) == MonitoringPolicy(
        zone_entry_confirm_seconds=1.1,
        zone_exit_confirm_seconds=1.2,
        entry_zone_min_overlap_ratio=0.31,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=1.3,
        absence_confirmation_seconds=10.0,
        trusted_sample_max_gap_seconds=1.4,
        reidentification_max_gap_seconds=2.0,
        reidentification_min_score=0.41,
        reidentification_ambiguity_margin=0.07,
        incident_confirm_seconds=0.2,
        incident_clear_seconds=0.3,
        incident_rule_timings=(
            IncidentRuleTiming(
                rule_code=DISABLED_ZONE_UNAUTHORIZED,
                confirm_duration_seconds=0.01,
                clear_duration_seconds=0.02,
            ),
            IncidentRuleTiming(
                rule_code=EV_ZONE_UNAUTHORIZED,
                confirm_duration_seconds=0.03,
                clear_duration_seconds=0.04,
            ),
            IncidentRuleTiming(
                rule_code=EV_OVERSTAY,
                confirm_duration_seconds=0.05,
                clear_duration_seconds=0.06,
            ),
            IncidentRuleTiming(
                rule_code=BAD_PARKING,
                confirm_duration_seconds=0.07,
                clear_duration_seconds=0.08,
            ),
            IncidentRuleTiming(
                rule_code=OUT_OF_ZONE,
                confirm_duration_seconds=0.09,
                clear_duration_seconds=0.10,
            ),
            IncidentRuleTiming(
                rule_code=AISLE_BLOCK,
                confirm_duration_seconds=0.11,
                clear_duration_seconds=0.12,
            ),
            IncidentRuleTiming(
                rule_code=DOUBLE_PARKING,
                confirm_duration_seconds=0.13,
                clear_duration_seconds=0.14,
            ),
        ),
        zone_presence_min_overlap_ratio=0.32,
        assignment_min_overlap_ratio=0.52,
        assignment_ambiguous_margin=0.06,
        bad_parking_min_primary_overlap_ratio=0.76,
        bad_parking_min_secondary_overlap_ratio=0.26,
        out_of_zone_min_spot_overlap_ratio=0.51,
        blocking_relation_confirm_seconds=1.5,
        blocking_relation_clear_seconds=1.6,
        blocking_min_subject_overlap_ratio=0.43,
        blocking_min_egress_coverage_ratio=0.44,
        motion_window_seconds=0.8,
        motion_min_observation_span_seconds=0.21,
        motion_max_sample_gap_seconds=0.4,
        motion_stationary_threshold=0.03,
        motion_moving_threshold=0.11,
        motion_min_samples=4,
        motion_min_trend_consistency=0.61,
    )


def test_runtime_factory_constructs_pipeline_without_opening_resources(
    tmp_path: Path,
) -> None:
    import src.main as main

    calibration_path = _write_calibration(tmp_path / "calibration.json")
    model_path = tmp_path / "vehicle.engine"
    model_path.write_bytes(b"test-model")
    settings = _settings(
        tmp_path,
        calibration_path=calibration_path,
        model_path=model_path,
    )
    calibration_reference = calibration_fingerprint(
        calibration_path,
        settings.remap_balance,
    )["calibrationSha256"]
    zones = _zones(calibration_reference)
    context, *_ = _context(main, settings, zones)

    pipeline = main.build_runtime_monitoring_pipeline(context)

    assert isinstance(pipeline, main.MonitoringPipeline)


def test_calibration_mismatch_fails_before_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.main as main

    calibration_path = _write_calibration(tmp_path / "calibration.json")
    model_path = tmp_path / "vehicle.engine"
    model_path.write_bytes(b"test-model")
    settings = _settings(
        tmp_path,
        calibration_path=calibration_path,
        model_path=model_path,
    )
    zones = _zones("different-calibration")
    context, *_ = _context(main, settings, zones)
    composition_calls = _block_composition(main, monkeypatch)

    with pytest.raises(ValueError, match="calibrationReference"):
        main.build_runtime_monitoring_pipeline(context)

    assert composition_calls == []


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing-calibration", "calibration_path"),
        ("calibration-directory", "calibration_path"),
        ("invalid-calibration-json", "올바른 JSON"),
        ("missing-model", "vehicle_model_path"),
        ("model-directory", "vehicle_model_path"),
    ),
)
def test_invalid_asset_fails_before_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    import src.main as main

    calibration_path = tmp_path / "calibration.json"
    model_path = tmp_path / "vehicle.engine"

    if case == "calibration-directory":
        calibration_path.mkdir()
    elif case == "invalid-calibration-json":
        calibration_path.write_text("{", encoding="utf-8")
    elif case != "missing-calibration":
        _write_calibration(calibration_path)

    if case == "model-directory":
        model_path.mkdir()
    elif case != "missing-model":
        model_path.write_bytes(b"test-model")

    settings = _settings(
        tmp_path,
        calibration_path=calibration_path,
        model_path=model_path,
    )
    calibration_reference = (
        calibration_fingerprint(
            calibration_path,
            settings.remap_balance,
        )["calibrationSha256"]
        if calibration_path.is_file()
        and case != "invalid-calibration-json"
        else "unused-calibration"
    )
    zones = _zones(calibration_reference)
    context, *_ = _context(main, settings, zones)
    composition_calls = _block_composition(main, monkeypatch)

    with pytest.raises(ValueError, match=message):
        main.build_runtime_monitoring_pipeline(context)

    assert composition_calls == []


def test_invalid_computed_mask_bounds_fail_during_composition(
    tmp_path: Path,
) -> None:
    import src.main as main

    calibration_path = _write_calibration(tmp_path / "calibration.json")
    model_path = tmp_path / "vehicle.engine"
    model_path.write_bytes(b"test-model")
    settings = _settings(
        tmp_path,
        calibration_path=calibration_path,
        model_path=model_path,
    )
    calibration_reference = calibration_fingerprint(
        calibration_path,
        settings.remap_balance,
    )["calibrationSha256"]
    zones = _zones(
        calibration_reference,
        polygon=(
            (0.01, 0.2),
            (0.99, 0.2),
            (0.5, 0.8),
        ),
    )
    context, *_ = _context(main, settings, zones)

    with pytest.raises(ValueError, match="마스크 경계"):
        main.build_runtime_monitoring_pipeline(context)

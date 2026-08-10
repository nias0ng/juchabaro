"""실행 표면이 공유하는 MonitoringPolicy 조립 메타데이터 계약."""

from src.config.monitoring_policy import INCIDENT_RULE_TIMING_SPECS
from src.config.settings import Settings


def test_incident_rule_timing_specs_are_complete_unique_settings_fields() -> None:
    rule_codes = [spec.rule_code for spec in INCIDENT_RULE_TIMING_SPECS]
    field_names = [
        field_name
        for spec in INCIDENT_RULE_TIMING_SPECS
        for field_name in (spec.confirm_field, spec.clear_field)
    ]

    assert len(rule_codes) == len(set(rule_codes)) == 7
    assert len(field_names) == len(set(field_names)) == 14
    assert set(field_names).issubset(Settings.model_fields)
    assert {spec.group for spec in INCIDENT_RULE_TIMING_SPECS} == {
        "CONTEXT",
        "GEOMETRY",
        "RELATION",
    }

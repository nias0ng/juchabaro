"""배포·Viewer·live·replay가 공유하는 MonitoringPolicy 조립 계약.

각 실행 표면은 입력 방법만 소유하고, domain owner에 전달할 정책의 필드 매핑과
알려진 Incident 규칙 목록은 이 모듈에서 한 번만 정의한다. 수치 검증과 상태 전이는
계속 각 domain owner가 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.application.monitoring_factory import MonitoringPolicy
from src.parking.models import IncidentRuleTiming
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


@dataclass(frozen=True, slots=True)
class IncidentRuleTimingSpec:
    """설정 필드와 domain rule code 사이의 명시적 배포 매핑."""

    rule_code: str
    confirm_field: str
    clear_field: str
    default_confirm_seconds: float
    default_clear_seconds: float
    group: str


INCIDENT_RULE_TIMING_SPECS = (
    IncidentRuleTimingSpec(
        rule_code=DISABLED_ZONE_UNAUTHORIZED,
        confirm_field=(
            "incident_disabled_zone_unauthorized_confirm_seconds"
        ),
        clear_field="incident_disabled_zone_unauthorized_clear_seconds",
        default_confirm_seconds=0.0,
        default_clear_seconds=0.0,
        group="CONTEXT",
    ),
    IncidentRuleTimingSpec(
        rule_code=EV_ZONE_UNAUTHORIZED,
        confirm_field="incident_ev_zone_unauthorized_confirm_seconds",
        clear_field="incident_ev_zone_unauthorized_clear_seconds",
        default_confirm_seconds=0.0,
        default_clear_seconds=0.0,
        group="CONTEXT",
    ),
    IncidentRuleTimingSpec(
        rule_code=EV_OVERSTAY,
        confirm_field="incident_ev_overstay_confirm_seconds",
        clear_field="incident_ev_overstay_clear_seconds",
        default_confirm_seconds=0.0,
        default_clear_seconds=0.0,
        group="CONTEXT",
    ),
    IncidentRuleTimingSpec(
        rule_code=BAD_PARKING,
        confirm_field="incident_bad_parking_confirm_seconds",
        clear_field="incident_bad_parking_clear_seconds",
        default_confirm_seconds=0.5,
        default_clear_seconds=0.5,
        group="GEOMETRY",
    ),
    IncidentRuleTimingSpec(
        rule_code=OUT_OF_ZONE,
        confirm_field="incident_out_of_zone_confirm_seconds",
        clear_field="incident_out_of_zone_clear_seconds",
        default_confirm_seconds=0.5,
        default_clear_seconds=0.5,
        group="GEOMETRY",
    ),
    IncidentRuleTimingSpec(
        rule_code=AISLE_BLOCK,
        confirm_field="incident_aisle_block_confirm_seconds",
        clear_field="incident_aisle_block_clear_seconds",
        default_confirm_seconds=0.5,
        default_clear_seconds=0.5,
        group="GEOMETRY",
    ),
    IncidentRuleTimingSpec(
        rule_code=DOUBLE_PARKING,
        confirm_field="incident_double_parking_confirm_seconds",
        clear_field="incident_double_parking_clear_seconds",
        default_confirm_seconds=0.0,
        default_clear_seconds=0.0,
        group="RELATION",
    ),
)


class MonitoringPolicyConfig(Protocol):
    """MonitoringPolicy 조립에 필요한 설정 projection."""

    zone_entry_confirm_seconds: float
    zone_exit_confirm_seconds: float
    exit_reentry_confirmation_seconds: float
    entry_zone_min_overlap_ratio: float
    parking_confirm_seconds: float
    parking_move_confirm_seconds: float
    absence_confirmation_seconds: float
    trusted_sample_max_gap_seconds: float
    reidentification_max_gap_seconds: float
    reidentification_min_score: float
    reidentification_ambiguity_margin: float
    incident_confirm_seconds: float
    incident_clear_seconds: float
    incident_disabled_zone_unauthorized_confirm_seconds: float
    incident_disabled_zone_unauthorized_clear_seconds: float
    incident_ev_zone_unauthorized_confirm_seconds: float
    incident_ev_zone_unauthorized_clear_seconds: float
    incident_ev_overstay_confirm_seconds: float
    incident_ev_overstay_clear_seconds: float
    incident_bad_parking_confirm_seconds: float
    incident_bad_parking_clear_seconds: float
    incident_out_of_zone_confirm_seconds: float
    incident_out_of_zone_clear_seconds: float
    incident_aisle_block_confirm_seconds: float
    incident_aisle_block_clear_seconds: float
    incident_double_parking_confirm_seconds: float
    incident_double_parking_clear_seconds: float
    zone_presence_min_overlap_ratio: float
    assignment_min_overlap_ratio: float
    assignment_ambiguous_margin: float
    bad_parking_min_primary_overlap_ratio: float
    bad_parking_min_secondary_overlap_ratio: float
    out_of_zone_min_spot_overlap_ratio: float
    blocking_relation_confirm_seconds: float
    blocking_relation_clear_seconds: float
    blocking_min_subject_overlap_ratio: float
    blocking_min_egress_coverage_ratio: float
    motion_window_seconds: float
    motion_min_observation_span_seconds: float
    motion_max_sample_gap_seconds: float
    motion_stationary_threshold: float
    motion_moving_threshold: float
    motion_min_samples: int
    motion_min_trend_consistency: float


def build_incident_rule_timings(
    config: MonitoringPolicyConfig,
) -> tuple[IncidentRuleTiming, ...]:
    """알려진 모든 규칙의 debounce 정책을 설정 projection에서 만든다."""

    return tuple(
        IncidentRuleTiming(
            rule_code=spec.rule_code,
            confirm_duration_seconds=float(
                getattr(config, spec.confirm_field)
            ),
            clear_duration_seconds=float(getattr(config, spec.clear_field)),
        )
        for spec in INCIDENT_RULE_TIMING_SPECS
    )


def build_monitoring_policy(
    config: MonitoringPolicyConfig,
) -> MonitoringPolicy:
    """입력 표면의 설정을 해석 없이 공통 MonitoringPolicy로 투영한다."""

    return MonitoringPolicy(
        zone_entry_confirm_seconds=config.zone_entry_confirm_seconds,
        zone_exit_confirm_seconds=config.zone_exit_confirm_seconds,
        exit_reentry_confirmation_seconds=(
            config.exit_reentry_confirmation_seconds
        ),
        entry_zone_min_overlap_ratio=config.entry_zone_min_overlap_ratio,
        parking_confirm_seconds=config.parking_confirm_seconds,
        parking_move_confirm_seconds=config.parking_move_confirm_seconds,
        absence_confirmation_seconds=config.absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=(
            config.trusted_sample_max_gap_seconds
        ),
        reidentification_max_gap_seconds=(
            config.reidentification_max_gap_seconds
        ),
        reidentification_min_score=config.reidentification_min_score,
        reidentification_ambiguity_margin=(
            config.reidentification_ambiguity_margin
        ),
        incident_confirm_seconds=config.incident_confirm_seconds,
        incident_clear_seconds=config.incident_clear_seconds,
        incident_rule_timings=build_incident_rule_timings(config),
        zone_presence_min_overlap_ratio=(
            config.zone_presence_min_overlap_ratio
        ),
        assignment_min_overlap_ratio=config.assignment_min_overlap_ratio,
        assignment_ambiguous_margin=config.assignment_ambiguous_margin,
        bad_parking_min_primary_overlap_ratio=(
            config.bad_parking_min_primary_overlap_ratio
        ),
        bad_parking_min_secondary_overlap_ratio=(
            config.bad_parking_min_secondary_overlap_ratio
        ),
        out_of_zone_min_spot_overlap_ratio=(
            config.out_of_zone_min_spot_overlap_ratio
        ),
        blocking_relation_confirm_seconds=(
            config.blocking_relation_confirm_seconds
        ),
        blocking_relation_clear_seconds=(
            config.blocking_relation_clear_seconds
        ),
        blocking_min_subject_overlap_ratio=(
            config.blocking_min_subject_overlap_ratio
        ),
        blocking_min_egress_coverage_ratio=(
            config.blocking_min_egress_coverage_ratio
        ),
        motion_window_seconds=config.motion_window_seconds,
        motion_min_observation_span_seconds=(
            config.motion_min_observation_span_seconds
        ),
        motion_max_sample_gap_seconds=config.motion_max_sample_gap_seconds,
        motion_stationary_threshold=config.motion_stationary_threshold,
        motion_moving_threshold=config.motion_moving_threshold,
        motion_min_samples=config.motion_min_samples,
        motion_min_trend_consistency=config.motion_min_trend_consistency,
    )

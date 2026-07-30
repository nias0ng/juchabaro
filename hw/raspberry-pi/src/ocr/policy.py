"""OCR burst 크기와 anchor 선택 범위를 정의하는 공유 정책."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _AggregationPolicyLike(Protocol):
    min_valid_frames: int


class _GeometryConfigLike(Protocol):
    max_extrapolation_frames: int
    single_anchor_reuse_radius: int


@dataclass(frozen=True, slots=True)
class OcrPipelinePolicy:
    """
    단일 차량 OCR 이벤트의 프레임 및 anchor 선택 정책.

    ``frame_count``는 pipeline이 요구하는 시간순 burst 크기이며,
    ``early_anchor_candidate_count``는 앞쪽 anchor의 품질을 비교할
    첫 프레임 개수다. later anchor는 항상 마지막 프레임이고 detector
    anchor 수는 현재 geometry 계약에 따라 정확히 두 개다.
    """

    frame_count: int = 6
    early_anchor_candidate_count: int = 2

    def __post_init__(self) -> None:
        if (
            isinstance(self.frame_count, bool)
            or not isinstance(self.frame_count, int)
            or self.frame_count < 3
        ):
            raise ValueError(
                "frame_count는 3 이상의 정수여야 합니다."
            )

        if (
            isinstance(self.early_anchor_candidate_count, bool)
            or not isinstance(self.early_anchor_candidate_count, int)
            or not (
                1
                <= self.early_anchor_candidate_count
                < self.frame_count
            )
        ):
            raise ValueError(
                "early_anchor_candidate_count는 1 이상 "
                "frame_count 미만의 정수여야 합니다."
            )


def validate_ocr_policy_compatibility(
    policy: OcrPipelinePolicy,
    aggregation_policy: _AggregationPolicyLike,
    geometry_config: _GeometryConfigLike,
) -> None:
    """프레임·anchor 확장·집계 정책의 실행 가능한 조합을 검증한다."""

    min_valid_frames = aggregation_policy.min_valid_frames
    if min_valid_frames > policy.frame_count:
        raise ValueError(
            "min_valid_frames는 frame_count보다 클 수 없습니다: "
            f"min_valid_frames={min_valid_frames}, "
            f"frame_count={policy.frame_count}"
        )

    # Burst 끝의 later anchor는 재사용 반경 한쪽만 활용할 수 있으므로
    # 가장 적은 프레임을 만드는 경계 anchor를 기준으로 검사한다.
    single_anchor_frame_capacity = min(
        policy.frame_count,
        geometry_config.single_anchor_reuse_radius + 1,
    )
    if min_valid_frames > single_anchor_frame_capacity:
        raise ValueError(
            "single-anchor fallback이 aggregation 최소 유효 프레임을 "
            "만들 수 없습니다: "
            f"capacity={single_anchor_frame_capacity}, "
            f"min_valid_frames={min_valid_frames}"
        )

    # earlier anchor가 후보 범위의 가장 뒤쪽에서 선택되면 두 anchor 사이
    # 프레임 수가 최소가 된다. 왼쪽 외삽 가능 수까지 더한 최악 용량을
    # 기준으로 aggregation 최소 프레임을 만들 수 있는지 확인한다.
    latest_earlier_index = policy.early_anchor_candidate_count - 1
    two_anchor_frame_capacity = (
        policy.frame_count
        - latest_earlier_index
        + min(
            latest_earlier_index,
            geometry_config.max_extrapolation_frames,
        )
    )
    if min_valid_frames > two_anchor_frame_capacity:
        raise ValueError(
            "two-anchor geometry가 aggregation 최소 유효 프레임을 "
            "만들 수 없습니다: "
            f"capacity={two_anchor_frame_capacity}, "
            f"min_valid_frames={min_valid_frames}"
        )

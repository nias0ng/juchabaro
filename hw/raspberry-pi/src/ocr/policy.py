"""OCR burst 크기와 anchor 선택 범위를 정의하는 공유 정책."""

from __future__ import annotations

from dataclasses import dataclass


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

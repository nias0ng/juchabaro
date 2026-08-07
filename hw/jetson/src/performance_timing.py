"""Jetson frame 처리 구간의 비영속 wall-clock 계측.

판정 결과나 영속 상태에 관여하지 않고, 실제 camera worker 한 frame이 소비한
시간만 기록한다. 각 frame의 표본은 heartbeat 주기 동안 메모리에만 유지되며
평균과 p95를 출력한 뒤 폐기된다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean
from time import perf_counter
from typing import Mapping


STAGE_NAMES = (
    "rawRead",
    "colorConvert",
    "remap",
    "captureTotal",
    "detector",
    "trackingPostprocess",
    "commit",
    "evidence",
    "observer",
    "unaccounted",
    "total",
)


@dataclass
class FramePerformanceTiming:
    """한 frame의 단계별 elapsed time을 millisecond로 누적한다."""

    started_at: float = field(default_factory=perf_counter)
    _durations_ms: dict[str, float] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def record_seconds(self, stage: str, elapsed_seconds: float) -> None:
        """한 단계의 wall-clock 시간을 기록한다.

        동일 stage가 wrapper 여러 곳에서 기록될 수 있으므로 덮어쓰지 않고
        누적한다. 이 값은 운영 판정이 아니라 성능 진단에만 사용된다.
        """

        if stage not in STAGE_NAMES:
            raise ValueError(f"unknown performance timing stage: {stage}")
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0.0:
            raise ValueError("elapsed_seconds must be a finite non-negative number")
        self._durations_ms[stage] = (
            self._durations_ms.get(stage, 0.0) + elapsed_seconds * 1_000.0
        )

    def duration_ms(self, stage: str) -> float | None:
        """기록된 stage 시간을 반환하고, 미계측 stage는 ``None``을 반환한다."""

        return self._durations_ms.get(stage)

    def snapshot(self) -> Mapping[str, float]:
        """현재 frame timing의 복사본을 반환한다."""

        return dict(self._durations_ms)


@dataclass(frozen=True)
class StageTimingStatistics:
    """heartbeat window에서 계산한 한 stage의 평균과 nearest-rank p95."""

    average_ms: float
    p95_ms: float


class PerformanceTimingWindow:
    """frame timing 표본을 heartbeat 단위로 모으고 비우는 accumulator."""

    def __init__(self) -> None:
        self._samples: list[Mapping[str, float]] = []

    def add(self, timing: FramePerformanceTiming) -> None:
        self._samples.append(timing.snapshot())

    def take_summary(
        self,
    ) -> tuple[int, dict[str, StageTimingStatistics]]:
        """현재 window 요약을 반환하고 표본을 초기화한다."""

        samples, self._samples = self._samples, []
        summary: dict[str, StageTimingStatistics] = {}
        for stage in STAGE_NAMES:
            values = sorted(
                sample[stage] for sample in samples if stage in sample
            )
            if not values:
                continue
            p95_index = max(math.ceil(len(values) * 0.95) - 1, 0)
            summary[stage] = StageTimingStatistics(
                average_ms=fmean(values),
                p95_ms=values[p95_index],
            )
        return len(samples), summary

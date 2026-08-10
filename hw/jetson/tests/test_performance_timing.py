"""Frame wall-clock timing 집계의 단위 테스트."""

import pytest

from src.performance_timing import (
    FramePerformanceTiming,
    PerformanceTimingWindow,
)


def test_timing_window_reports_average_and_nearest_rank_p95_then_clears() -> None:
    window = PerformanceTimingWindow()
    for milliseconds in range(1, 21):
        timing = FramePerformanceTiming(started_at=0.0)
        timing.record_seconds("rawRead", milliseconds / 1_000.0)
        window.add(timing)

    frame_count, summary = window.take_summary()

    assert frame_count == 20
    assert summary["rawRead"].average_ms == pytest.approx(10.5)
    assert summary["rawRead"].p95_ms == pytest.approx(19.0)
    assert window.take_summary() == (0, {})


def test_frame_timing_accumulates_repeated_stage_measurements() -> None:
    timing = FramePerformanceTiming(started_at=0.0)

    timing.record_seconds("commit", 0.010)
    timing.record_seconds("commit", 0.005)

    assert timing.duration_ms("commit") == pytest.approx(15.0)
    assert timing.snapshot()["commit"] == pytest.approx(15.0)


@pytest.mark.parametrize("seconds", [-1.0, float("nan"), float("inf")])
def test_frame_timing_rejects_invalid_duration(seconds: float) -> None:
    timing = FramePerformanceTiming(started_at=0.0)

    with pytest.raises(ValueError):
        timing.record_seconds("rawRead", seconds)

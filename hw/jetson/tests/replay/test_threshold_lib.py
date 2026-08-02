"""파일럿 영상 리플레이 원본 데이터에서 임계값 후보를 뽑고 분석하는 라이브러리(466/T-18).

CLI(scripts/replay_pilot_video.py)를 문턱값마다 재실행하지 않는다 — 확인시간을 0으로 두고
한 번만 돌리면 각 방문의 실제 체류시간이 그대로 로그에 남으므로(zone_visit_tracker.py의
entry_confirm_seconds<=0/exit_confirm_seconds<=0 경로), 임의의 문턱값에 대해
"이 방문이 그 문턱값에서도 확정됐을까"를 dwellSeconds >= threshold로 계산할 수 있다.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.threshold_lib import (
    build_candidates,
    compute_dwell_seconds,
    evaluate_threshold,
    load_completed_visits,
    recommend_threshold,
    sweep_thresholds,
    ts_to_video_seconds,
    would_confirm,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_load_completed_visits_filters_by_zone_and_state(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 3, "state": "OUTSIDE", "zoneVisitId": "v1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "exitedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 1, "state": "OUTSIDE", "zoneVisitId": "v2",
         "enteredAt": "1970-01-01T00:00:05+00:00", "exitedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 7, "state": "ENTERING", "zoneVisitId": "v3",
         "enteredAt": None, "exitedAt": None},
        {"zoneId": 7, "state": "OUTSIDE", "zoneVisitId": "v4",
         "enteredAt": "1970-01-01T00:00:10+00:00", "exitedAt": "1970-01-01T00:00:12+00:00"},
    ])

    records = load_completed_visits(path)

    assert {r["zoneVisitId"] for r in records} == {"v1", "v4"}


def test_compute_dwell_seconds():
    record = {"enteredAt": "1970-01-01T00:00:05+00:00", "exitedAt": "1970-01-01T00:00:08.500000+00:00"}

    assert compute_dwell_seconds(record) == pytest.approx(3.5)


def test_compute_dwell_seconds_returns_none_for_incomplete_visit():
    assert compute_dwell_seconds({"enteredAt": None, "exitedAt": "1970-01-01T00:00:08+00:00"}) is None


def test_compute_dwell_seconds_returns_none_for_missing_exit_time():
    assert compute_dwell_seconds({"enteredAt": "1970-01-01T00:00:05+00:00", "exitedAt": None}) is None


def test_build_candidates_skips_incomplete_and_computes_dwell(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 3, "state": "OUTSIDE", "zoneVisitId": "v1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "exitedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 3, "state": "OUTSIDE", "zoneVisitId": "v2",
         "enteredAt": None, "exitedAt": "1970-01-01T00:00:08+00:00"},
    ])

    candidates = build_candidates("video1", path)

    assert len(candidates) == 1
    assert candidates[0]["video"] == "video1"
    assert candidates[0]["visitId"] == "v1"
    assert candidates[0]["zoneId"] == 3
    assert candidates[0]["dwellSeconds"] == pytest.approx(3.0)


def test_ts_to_video_seconds():
    assert ts_to_video_seconds("1970-01-01T00:00:05.500000+00:00") == pytest.approx(5.5)


CANDIDATES = [
    {"video": "video1", "visitId": "v1", "zoneId": 3, "enteredAt": "", "exitedAt": "", "dwellSeconds": 0.5},
    {"video": "video1", "visitId": "v2", "zoneId": 3, "enteredAt": "", "exitedAt": "", "dwellSeconds": 4.0},
    {"video": "video2", "visitId": "v3", "zoneId": 7, "enteredAt": "", "exitedAt": "", "dwellSeconds": 1.5},
]
LABELS = {
    "v1": {"violation": False, "ambiguous": False, "note": "인접 칸 후진 주차 중 스침"},
    "v2": {"violation": True, "ambiguous": False, "note": "실제 정차"},
    "v3": {"violation": False, "ambiguous": False, "note": "통행 중 스침"},
}


def test_would_confirm():
    assert would_confirm(3.0, 2.0) is True
    assert would_confirm(1.0, 2.0) is False
    assert would_confirm(2.0, 2.0) is True  # 경계값은 확정으로 본다(ZoneVisitTracker와 동일)


def test_evaluate_threshold_counts_false_positive_and_false_negative():
    # threshold=1.0: v1(0.5s,오탐아님)->미확정, v2(4.0s,진짜)->확정, v3(1.5s,오탐)->확정(FP)
    result = evaluate_threshold(CANDIDATES, LABELS, 1.0)

    assert result["falsePositiveCount"] == 1
    assert result["falsePositiveVisitIds"] == ["v3"]
    assert result["falseNegativeCount"] == 0


def test_evaluate_threshold_raises_on_missing_label():
    with pytest.raises(ValueError, match="v1"):
        evaluate_threshold(CANDIDATES, {}, 1.0)


def test_sweep_thresholds_returns_one_result_per_threshold():
    results = sweep_thresholds(CANDIDATES, LABELS, [0.1, 1.0, 2.0])

    assert [r["thresholdSeconds"] for r in results] == [0.1, 1.0, 2.0]


def test_recommend_threshold_picks_smallest_zero_false_positive():
    # threshold=2.0: v1(0.5)->no, v3(1.5)->no(1.5<2.0), v2(4.0)->yes(진짜) → FP=0
    results = sweep_thresholds(CANDIDATES, LABELS, [0.1, 1.0, 2.0, 3.0])

    recommendation = recommend_threshold(results)

    assert recommendation["thresholdSeconds"] == 2.0
    assert recommendation["zeroFalsePositive"] is True


def test_recommend_threshold_falls_back_when_zero_fp_impossible_in_grid():
    candidates = [{"visitId": "x1", "zoneId": 3, "video": "v", "enteredAt": "", "exitedAt": "", "dwellSeconds": 100.0}]
    labels = {"x1": {"violation": False, "ambiguous": False, "note": "그리드 범위 내에서 항상 확정되는 예시"}}
    results = sweep_thresholds(candidates, labels, [1.0, 5.0, 10.0])

    recommendation = recommend_threshold(results)

    assert recommendation["zeroFalsePositive"] is False
    assert recommendation["falsePositiveCount"] == 1
    assert recommendation["thresholdSeconds"] == 1.0  # 오탐이 어차피 안 사라지면 그나마 작은 값

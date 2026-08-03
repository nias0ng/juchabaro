"""`scripts/threshold_lib.py`의 단위 테스트(466/T-18).

방문 필터링·체류시간 계산·문턱값 스윕/추천·프레임 추출·재진입(플리커) 간격 탐지
각 함수를 raw-pass JSONL 픽스처로 검증한다. `build_flicker_gaps` 관련 픽스처는
`--zone-entry-confirm-seconds 0`에서 실제로 나오는 상태값(INSIDE)을 그대로
반영해야 한다 — ENTERING으로 손으로 지어낸 픽스처는 실제 파이프라인 출력과
어긋나 버그를 가려버린다(리뷰에서 잡힌 사례 참고).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from scripts.threshold_lib import (
    build_candidates,
    build_flicker_gaps,
    compute_dwell_seconds,
    evaluate_threshold,
    extract_frames_for_candidate,
    load_completed_visits,
    recommend_threshold,
    sweep_thresholds,
    ts_to_video_seconds,
    would_confirm,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import ZoneVisit, ZoneVisitState
from src.replay.zone_visit_publisher import zone_visit_to_jsonable

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_load_completed_visits_filters_by_zone_and_state(tmp_path):
    """RESTRICTED_ZONE_IDS={1, 4}(config/zone_definition.pilot.json의 EV_CHARGING/DISABLED)
    만 남기고, 같은 파일의 GENERAL 구역(zoneId=3)은 걸러야 한다."""

    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 1, "state": "ENDED", "zoneVisitId": "v1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 3, "state": "ENDED", "zoneVisitId": "v2",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 4, "state": "ENTERING", "zoneVisitId": "v3",
         "enteredAt": None, "endedAt": None},
        {"zoneId": 4, "state": "ENDED", "zoneVisitId": "v4",
         "enteredAt": "1970-01-01T00:00:10+00:00", "endedAt": "1970-01-01T00:00:12+00:00"},
    ])

    records = load_completed_visits(path)

    assert {r["zoneVisitId"] for r in records} == {"v1", "v4"}


def test_compute_dwell_seconds():
    record = {"enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08.500000+00:00"}

    assert compute_dwell_seconds(record) == pytest.approx(3.5)


def test_compute_dwell_seconds_returns_none_for_incomplete_visit():
    assert compute_dwell_seconds({"enteredAt": None, "endedAt": "1970-01-01T00:00:08+00:00"}) is None


def test_compute_dwell_seconds_returns_none_for_missing_exit_time():
    assert compute_dwell_seconds({"enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": None}) is None


def test_build_candidates_skips_incomplete_and_computes_dwell(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 4, "state": "ENDED", "zoneVisitId": "v1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
        {"zoneId": 4, "state": "ENDED", "zoneVisitId": "v2",
         "enteredAt": None, "endedAt": "1970-01-01T00:00:08+00:00"},
    ])

    candidates = build_candidates("video1", path)

    assert len(candidates) == 1
    assert candidates[0]["video"] == "video1"
    assert candidates[0]["visitId"] == "v1"
    assert candidates[0]["zoneId"] == 4
    assert candidates[0]["dwellSeconds"] == pytest.approx(3.0)


def test_build_candidates_recognizes_real_producer_output_for_restricted_zone(tmp_path):
    """`load_completed_visits`/`RESTRICTED_ZONE_IDS`를 손으로 쓴 dict가 아니라
    실제 wire 생산자(`zone_visit_to_jsonable`)와 실제 config/zone_definition.pilot.json의
    zoneId(EV_CHARGING=1)로 검증한다.

    RESTRICTED_ZONE_IDS가 옛 ai/tracking/zones_pilot.json 값(3/7)으로 굳어 있던
    적이 있었는데, 이 파일의 픽스처가 전부 손으로 쓴 dict라 그 드리프트를
    아무것도 잡아내지 못했다(리뷰에서 잡힌 사례). 이 테스트는 실제 ZoneVisit을
    실제 직렬화 함수에 통과시켜 생산자·소비자 어휘가 어긋나면 반드시 깨지게 한다.
    """

    visit = ZoneVisit(
        visit_id=UUID(int=101),
        physical_vehicle_id=UUID(int=102),
        zone_id=1,  # config/zone_definition.pilot.json: zoneId 1 == EV_CHARGING
        zone_definition_version=3,
        state=ZoneVisitState.ENDED,
        observation=ObservationStatus(
            state=ObservationState.OBSERVED, last_reliable_observed_at=T0
        ),
        entry_trusted_seconds=1.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=2,
        created_at=T0,
        updated_at=T0,
        entered_candidate_at=T0,
        entered_at=T0,
        ended_at=T0 + timedelta(seconds=4.0),
        termination_reason="ZONE_EXIT_CONFIRMED",
    )

    path = tmp_path / "zone_visits.jsonl"
    path.write_text(json.dumps(zone_visit_to_jsonable(visit)) + "\n", encoding="utf-8")

    candidates = build_candidates("video1", path)

    assert len(candidates) == 1
    assert candidates[0]["visitId"] == str(visit.visit_id)
    assert candidates[0]["zoneId"] == 1
    assert candidates[0]["dwellSeconds"] == pytest.approx(4.0)


def test_ts_to_video_seconds():
    assert ts_to_video_seconds("1970-01-01T00:00:05.500000+00:00") == pytest.approx(5.5)


CANDIDATES = [
    {"video": "video1", "visitId": "v1", "zoneId": 3, "enteredAt": "", "endedAt": "", "dwellSeconds": 0.5},
    {"video": "video1", "visitId": "v2", "zoneId": 3, "enteredAt": "", "endedAt": "", "dwellSeconds": 4.0},
    {"video": "video2", "visitId": "v3", "zoneId": 7, "enteredAt": "", "endedAt": "", "dwellSeconds": 1.5},
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
    candidates = [{"visitId": "x1", "zoneId": 3, "video": "v", "enteredAt": "", "endedAt": "", "dwellSeconds": 100.0}]
    labels = {"x1": {"violation": False, "ambiguous": False, "note": "그리드 범위 내에서 항상 확정되는 예시"}}
    results = sweep_thresholds(candidates, labels, [1.0, 5.0, 10.0])

    recommendation = recommend_threshold(results)

    assert recommendation["zeroFalsePositive"] is False
    assert recommendation["falsePositiveCount"] == 1
    assert recommendation["thresholdSeconds"] == 1.0  # 오탐이 어차피 안 사라지면 그나마 작은 값


def test_extract_frames_for_candidate_returns_expected_count(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    video_path = tmp_path / "tiny.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (32, 32))
    for _ in range(50):
        writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
    writer.release()

    out_dir = tmp_path / "frames"
    paths = extract_frames_for_candidate(
        video_path, center_seconds=2.5, out_dir=out_dir, before_seconds=1.0, after_seconds=1.0, step_seconds=1.0
    )

    assert len(paths) == 3  # t-1.0s, t+0.0s, t+1.0s
    assert all(p.exists() for p in paths)


def test_build_flicker_gaps_pairs_same_vehicle_reentry(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 3, "state": "ENDED", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
        # raw-pass(--zone-entry-confirm-seconds 0)에서는 새 방문이 ENTERING을 거치지
        # 않고 첫 관측에서 곧바로 INSIDE로 승격되어 기록된다(zone_visit_tracker.py의
        # _open_candidate 참고) — 그래서 픽스처도 INSIDE로 둔다.
        {"zoneId": 3, "state": "INSIDE", "zoneVisitId": "v2", "physicalVehicleId": "pv-1",
         "enteredCandidateAt": "1970-01-01T00:00:08.400000+00:00"},
        {"zoneId": 3, "state": "INSIDE", "zoneVisitId": "v3", "physicalVehicleId": "pv-2",
         "enteredCandidateAt": "1970-01-01T00:00:20+00:00"},
    ])

    gaps = build_flicker_gaps("video1", path)

    assert len(gaps) == 1
    assert gaps[0]["zoneVisitId"] == "v1"
    assert gaps[0]["nextVisitId"] == "v2"
    assert gaps[0]["gapSeconds"] == pytest.approx(0.4)


def test_build_flicker_gaps_ignores_visits_with_no_later_reentry(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        # v1 자신의 INSIDE 전이 — 같은 (physicalVehicleId, zoneId) 키로 entries_by_key에
        # 들어가지만 자기 자신의 endedAt과 짝지어질 수 있는 후보다. zoneVisitId가
        # exit_record와 같으므로 자기 자신과의 짝짓기 가드로 걸러져야 한다(시각상으로도
        # endedAt보다 이전이라 이중으로 걸러진다).
        {"zoneId": 3, "state": "INSIDE", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredCandidateAt": "1970-01-01T00:00:02+00:00"},
        {"zoneId": 3, "state": "ENDED", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
    ])

    assert build_flicker_gaps("video1", path) == []


def test_build_flicker_gaps_ignores_reentry_from_different_vehicle(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 3, "state": "ENDED", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
        # 시각상으로는 endedAt 직후라 재진입처럼 보이지만 physicalVehicleId가 다르다 —
        # 시각 비교만으로는 걸러지지 않고 키(physicalVehicleId, zoneId) 매칭이 걸러내야 한다.
        {"zoneId": 3, "state": "INSIDE", "zoneVisitId": "v2", "physicalVehicleId": "pv-2",
         "enteredCandidateAt": "1970-01-01T00:00:08.400000+00:00"},
    ])

    assert build_flicker_gaps("video1", path) == []


def test_build_flicker_gaps_excludes_self_pairing_with_own_zone_visit_id(tmp_path):
    # 방문 하나의 생애주기 전부(INSIDE 진입 -> ENDED 종료)가 같은 zoneVisitId를
    # 공유한다. enteredCandidateAt이 endedAt보다 뒤(재기록/시계 오차 등으로 실제
    # 발생할 수 있는 값)라 시각 비교만으로는 걸러지지 않는다 —
    # test_build_flicker_gaps_pairs_same_vehicle_reentry와 구조가 같지만
    # zoneVisitId가 같다는 점만 다르다. zoneVisitId 배제 가드가 없으면 이 INSIDE
    # 레코드가 자기 자신의 ENDED와 재진입으로 잘못 짝지어져 가짜 플리커 간격을
    # 만들어낸다.
    path = tmp_path / "zone_visits.jsonl"
    _write_jsonl(path, [
        {"zoneId": 3, "state": "INSIDE", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredCandidateAt": "1970-01-01T00:00:08.400000+00:00"},
        {"zoneId": 3, "state": "ENDED", "zoneVisitId": "v1", "physicalVehicleId": "pv-1",
         "enteredAt": "1970-01-01T00:00:05+00:00", "endedAt": "1970-01-01T00:00:08+00:00"},
    ])

    assert build_flicker_gaps("video1", path) == []

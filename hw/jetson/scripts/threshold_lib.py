"""파일럿 영상 리플레이 원본 데이터에서 임계값 후보를 뽑고 분석하는 라이브러리(466/T-18).

CLI(scripts/replay_pilot_video.py)를 문턱값마다 재실행하지 않는다 — 확인시간을 0으로 두고
한 번만 돌리면 각 방문의 실제 체류시간이 그대로 로그에 남으므로(zone_visit_tracker.py의
entry_confirm_seconds<=0/exit_confirm_seconds<=0 경로), 임의의 문턱값에 대해
"이 방문이 그 문턱값에서도 확정됐을까"를 dwellSeconds >= threshold로 계산할 수 있다.

측정 대상은 zone_entry_confirm_seconds/zone_exit_confirm_seconds뿐이다. movement_epsilon은
현재 파이프라인에서 관측 가능한 효과가 없어 범위 밖이다(설계 문서 참고).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# VideoFileFrameSource가 t0으로 쓰는 기준점과 같다 — captured_at을 영상 재생 시간(초)으로
# 되돌리려면 같은 기준점이 필요하다(camera/frame_source.py의 EPOCH 참고).
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# 전용구역(§4.7의 즉시 위반 판정 대상)만 후보로 삼는다 — ai/tracking/zones_pilot.json 기준.
RESTRICTED_ZONE_IDS = {3, 7}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_completed_visits(zone_visits_path: Path) -> list[dict[str, Any]]:
    """`--out-zone-visits` JSONL에서 전용구역으로 향한, 완결된(OUTSIDE) 방문만 남긴다."""

    return [
        record
        for record in _read_jsonl(zone_visits_path)
        if record["zoneId"] in RESTRICTED_ZONE_IDS and record["state"] == "OUTSIDE"
    ]


def compute_dwell_seconds(record: dict[str, Any]) -> float | None:
    """`enteredAt`~`exitedAt` 체류시간(초). 둘 중 하나라도 없으면 미완결 방문이라 None."""

    entered_at, exited_at = record.get("enteredAt"), record.get("exitedAt")
    if entered_at is None or exited_at is None:
        return None
    return (datetime.fromisoformat(exited_at) - datetime.fromisoformat(entered_at)).total_seconds()


def build_candidates(video: str, zone_visits_path: Path) -> list[dict[str, Any]]:
    """완결된 전용구역 방문마다 체류시간을 계산해 후보 레코드를 만든다."""

    candidates = []
    for record in load_completed_visits(zone_visits_path):
        dwell = compute_dwell_seconds(record)
        if dwell is None:
            continue
        candidates.append({
            "video": video,
            "visitId": record["zoneVisitId"],
            "zoneId": record["zoneId"],
            "enteredAt": record["enteredAt"],
            "exitedAt": record["exitedAt"],
            "dwellSeconds": dwell,
        })
    return candidates


def ts_to_video_seconds(iso_timestamp: str) -> float:
    """`VideoFileFrameSource`가 t0=EPOCH로 찍은 ISO 타임스탬프를 영상 재생 시간(초)으로 되돌린다."""

    return (datetime.fromisoformat(iso_timestamp) - EPOCH).total_seconds()


def would_confirm(dwell_seconds: float, threshold_seconds: float) -> bool:
    """이 체류시간이 주어진 확인시간 문턱값에서 확정됐을지 여부.

    `InMemoryZoneVisitTracker._advance_entering`의 확정 조건(누적 관측 시간 >=
    entry_confirm_seconds)과 같은 부등식이다 — 라벨링 없이 산수로 재현한다.
    """

    return dwell_seconds >= threshold_seconds


def evaluate_threshold(
    candidates: list[dict[str, Any]], labels: dict[str, dict[str, Any]], threshold_seconds: float
) -> dict[str, Any]:
    """이 문턱값에서의 오탐·놓친 위반 개수를 센다.

    후보 전부가 라벨을 갖고 있어야 한다 — 라벨 없는 후보가 조용히 빠지면 측정
    자체가 무의미해지므로 에러로 막는다(ZoneRegistry의 중복 검사와 같은 원칙).
    """

    missing = [c["visitId"] for c in candidates if c["visitId"] not in labels]
    if missing:
        raise ValueError(f"라벨이 없는 후보가 있습니다: {missing}")

    false_positives: list[str] = []
    false_negatives: list[str] = []
    for candidate in candidates:
        label = labels[candidate["visitId"]]
        confirmed = would_confirm(candidate["dwellSeconds"], threshold_seconds)
        if label["violation"] and not confirmed:
            false_negatives.append(candidate["visitId"])
        elif not label["violation"] and confirmed:
            false_positives.append(candidate["visitId"])

    return {
        "thresholdSeconds": threshold_seconds,
        "falsePositiveCount": len(false_positives),
        "falsePositiveVisitIds": false_positives,
        "falseNegativeCount": len(false_negatives),
        "falseNegativeVisitIds": false_negatives,
    }


def sweep_thresholds(
    candidates: list[dict[str, Any]], labels: dict[str, dict[str, Any]], threshold_grid: list[float]
) -> list[dict[str, Any]]:
    """문턱값 후보 각각에 대해 `evaluate_threshold`를 돌려 표로 반환한다."""

    return [evaluate_threshold(candidates, labels, threshold) for threshold in threshold_grid]


def recommend_threshold(sweep_results: list[dict[str, Any]]) -> dict[str, Any]:
    """오탐 0건을 만드는 가장 작은 문턱값을 추천한다.

    오탐 0건이 불가능하면(그리드 안에서), 오탐이 가장 적은 문턱값 중 가장 작은 값을
    추천하되 `zeroFalsePositive=False`로 표시해 트레이드오프가 있었음을 알린다 —
    오탐이 그대로면 문턱값을 더 키워도 놓친 위반의 확정만 늦어질 뿐이다.
    """

    zero_fp = [r for r in sweep_results if r["falsePositiveCount"] == 0]
    if zero_fp:
        best = min(zero_fp, key=lambda r: r["thresholdSeconds"])
        return {**best, "zeroFalsePositive": True}
    best = min(sweep_results, key=lambda r: (r["falsePositiveCount"], r["thresholdSeconds"]))
    return {**best, "zeroFalsePositive": False}

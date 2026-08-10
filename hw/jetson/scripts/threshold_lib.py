"""파일럿 영상 리플레이 원본 데이터에서 임계값 후보를 뽑고 분석하는 라이브러리(466/T-18).

CLI(scripts/replay_pilot_video.py)를 문턱값마다 재실행하지 않는다 — 확인시간을 0으로 두고
한 번만 돌리면 각 방문의 실제 체류시간이 그대로 로그에 남으므로(zone_visit_tracker.py의
entry_confirm_seconds<=0/exit_confirm_seconds<=0 경로), 임의의 문턱값에 대해
"이 방문이 그 문턱값에서도 확정됐을까"를 dwellSeconds >= threshold로 계산할 수 있다.

측정 대상은 zone_entry_confirm_seconds/zone_exit_confirm_seconds뿐이다. motion evidence의
시간 창·정규화 변위·추세 임계값은 별도 MotionEstimator replay/export로 검증한다. 이 helper가
서로 다른 owner의 threshold를 한 번에 최적화하지 않는 것은 의도적이다.

**입력 포맷은 464 기준이다.** 방문 종료 상태는 ENDED(옛 OUTSIDE), 종료 시각 필드는
endedAt(옛 exitedAt)이다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# VideoFileFrameSource가 t0으로 쓰는 기준점과 같다 — captured_at을 영상 재생 시간(초)으로
# 되돌리려면 같은 기준점이 필요하다(camera/frame_source.py의 EPOCH 참고).
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# 전용구역(§4.7의 즉시 위반 판정 대상)만 후보로 삼는다 —
# config/zone_definition.pilot.json 기준(zoneId 4=DISABLED, zoneId 5=EV_CHARGING).
# 리뷰에서 잡힌 사례: 이 상수는 예전 ai/tracking/zones_pilot.json(zoneId 3/7)
# 기준값이 그대로 남아 있던 적이 있다 — zones 파일을 바꿀 때마다 반드시 같이 검토한다.
RESTRICTED_ZONE_IDS = {4, 5}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_completed_visits(zone_visits_path: Path) -> list[dict[str, Any]]:
    """`--out-zone-visits` JSONL에서 전용구역으로 향한, 완결된(ENDED) 방문만 남긴다.

    464에서 종료 상태가 OUTSIDE 하나에서 ENDED/CANCELED 둘로 갈렸다. 여기서
    보는 것은 ENDED뿐이다 — CANCELED는 진입이 확정되기 전에 사라진 방문이라
    `enteredAt`이 없어 체류시간 자체가 없다. 이 측정이 요구하는 raw-pass
    설정(`--zone-entry-confirm-seconds 0`)에서는 모든 방문이 첫 관측에서 곧바로
    INSIDE로 승격되므로 CANCELED가 아예 나오지 않는다.
    """

    return [
        record
        for record in _read_jsonl(zone_visits_path)
        if record["zoneId"] in RESTRICTED_ZONE_IDS and record["state"] == "ENDED"
    ]


def compute_dwell_seconds(record: dict[str, Any]) -> float | None:
    """`enteredAt`~`endedAt` 체류시간(초). 둘 중 하나라도 없으면 미완결 방문이라 None."""

    entered_at, ended_at = record.get("enteredAt"), record.get("endedAt")
    if entered_at is None or ended_at is None:
        return None
    return (datetime.fromisoformat(ended_at) - datetime.fromisoformat(entered_at)).total_seconds()


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
            "endedAt": record["endedAt"],
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


def extract_frames_for_candidate(
    video_path: Path,
    center_seconds: float,
    out_dir: Path,
    *,
    before_seconds: float = 2.0,
    after_seconds: float = 2.0,
    step_seconds: float = 1.0,
) -> list[Path]:
    """`center_seconds` 전후 구간의 프레임을 PNG로 추출해 `out_dir`에 저장한다.

    정지 프레임 한 장으로는 "통과 중"과 "차를 대는 중"을 구분할 수 없어 짧은
    구간을 여러 장 뽑는다. `hw/jetson` 자체 환경에는 cv2가 없을 수 있어 이
    함수를 부르는 쪽(Task 4의 실행 절차)은 cv2가 설치된 인터프리터로 돌려야
    한다 — 예: `ai/training/.venv`.
    """

    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {video_path}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    paths: list[Path] = []
    t = center_seconds - before_seconds
    end = center_seconds + after_seconds
    while t <= end + 1e-9:
        frame_index = max(0, int(round(t * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if ok:
            offset_ms = int(round((t - center_seconds) * 1000))
            frame_path = out_dir / f"t{offset_ms:+06d}ms.png"
            cv2.imwrite(str(frame_path), frame)
            paths.append(frame_path)
        t += step_seconds
    capture.release()
    return paths


def build_flicker_gaps(video: str, zone_visits_path: Path) -> list[dict[str, Any]]:
    """같은 `physicalVehicleId`·`zoneId`가 방문을 닫고 곧바로 새 방문을 여는 간격을 모은다.

    실제로 구역을 떠난 게 아니라 탐지가 잠깐 끊긴 것일 가능성이 있는 재진입
    후보다. `zone_exit_confirm_seconds`가 이 간격보다 커야 그 순간의 RESOLVE를
    막을 수 있다 — 위반 여부 라벨은 필요 없다.

    이 측정 절차가 요구하는 raw-pass 설정(`--zone-entry-confirm-seconds 0`)에서는
    `zone_visit_tracker.py`의 `_open_candidate`가 새 방문을 ENTERING으로 두지 않고
    첫 관측에서 곧바로 INSIDE로 승격해 반환한다 — 따라서 재진입 후보는 INSIDE
    상태로 기록에 남는다. `enteredCandidateAt`은 같은 `_open_candidate` 호출에서
    채워지므로 ENTERING이었다면 가졌을 값과 동일하다.

    닫힌 방문은 464 기준 ENDED다(옛 OUTSIDE). CANCELED는 raw-pass에서 나오지
    않으므로 여기서도 보지 않는다 — `load_completed_visits` 참고.
    """

    records = _read_jsonl(zone_visits_path)
    exits_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    entries_by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        key = (record["physicalVehicleId"], record["zoneId"])
        if record["state"] == "ENDED":
            exits_by_key.setdefault(key, []).append(record)
        elif record["state"] == "INSIDE":
            entries_by_key.setdefault(key, []).append(record)

    gaps: list[dict[str, Any]] = []
    for key, exits in exits_by_key.items():
        entries = entries_by_key.get(key, [])
        for exit_record in exits:
            exited_at = datetime.fromisoformat(exit_record["endedAt"])
            later_entries = [
                entry for entry in entries
                if entry["zoneVisitId"] != exit_record["zoneVisitId"]
                and datetime.fromisoformat(entry["enteredCandidateAt"]) > exited_at
            ]
            if not later_entries:
                continue
            next_entry = min(
                later_entries, key=lambda e: datetime.fromisoformat(e["enteredCandidateAt"])
            )
            gap_seconds = (datetime.fromisoformat(next_entry["enteredCandidateAt"]) - exited_at).total_seconds()
            gaps.append({
                "video": video,
                "zoneVisitId": exit_record["zoneVisitId"],
                "nextVisitId": next_entry["zoneVisitId"],
                "gapSeconds": gap_seconds,
            })
    return gaps

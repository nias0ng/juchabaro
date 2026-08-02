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

"""JsonlOutbox 회귀 테스트 (440)."""

import json
from datetime import datetime, timezone

import pytest
from src.communication.outbox import JsonlOutbox, OutboxError, transition_to_jsonable
from src.parking.models import (
    Incident,
    IncidentKey,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
)

NOW = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)


def make_open_transition() -> IncidentTransition:
    key = IncidentKey(physical_vehicle_id="pv-1", rule_code="DISABLED_ZONE_UNAUTHORIZED", zone_visit_id="visit-1", zone_id=7)
    incident = Incident(
        incident_id="inc-1",
        key=key,
        state=IncidentState.EDGE_CONFIRMED,
        revision=1,
        first_observed_at=NOW,
        confirmed_at=NOW,
    )
    return IncidentTransition(transition_type=IncidentTransitionType.OPEN, incident=incident)


def test_transition_to_jsonable_maps_open_fields():
    payload = transition_to_jsonable(make_open_transition())

    assert payload["transitionType"] == "OPEN"
    assert payload["incidentId"] == "inc-1"
    assert payload["revision"] == 1
    assert payload["state"] == "EDGE_CONFIRMED"
    assert payload["ruleCode"] == "DISABLED_ZONE_UNAUTHORIZED"
    assert payload["physicalVehicleId"] == "pv-1"
    assert payload["zoneVisitId"] == "visit-1"
    assert payload["zoneId"] == 7
    assert payload["parkingEpisodeId"] is None
    assert payload["victimPhysicalVehicleId"] is None
    assert payload["firstObservedAt"] == NOW.isoformat()
    assert payload["confirmedAt"] == NOW.isoformat()
    assert payload["resolvedAt"] is None


def test_transition_to_jsonable_is_actually_json_serializable():
    """dict가 아니라 json.dumps를 실제로 통과하는지 확인 — datetime/NewType이
    섞여 있으면 dict 단정만으로는 직렬화 실패를 못 잡는다."""
    payload = transition_to_jsonable(make_open_transition())

    json.dumps(payload)  # 예외 없이 통과해야 한다


def test_append_writes_one_json_line_per_call(tmp_path):
    outbox = JsonlOutbox(tmp_path / "outbox.jsonl")

    outbox.append(make_open_transition())
    outbox.append(make_open_transition())

    lines = (tmp_path / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["incidentId"] == "inc-1"


def test_creates_missing_parent_directories(tmp_path):
    nested = tmp_path / "a" / "b" / "outbox.jsonl"

    JsonlOutbox(nested)

    assert nested.parent.is_dir()


def test_append_raises_outbox_error_when_path_is_a_directory(tmp_path):
    """쓸 수 없는 경로(디렉터리)를 파일로 열려고 하면 OSError가 나야 하고,
    판정 루프가 그걸 그대로 받을 게 아니라 OutboxError로 감싸져야 한다."""
    directory_path = tmp_path / "not_a_file"
    directory_path.mkdir()
    outbox = JsonlOutbox(directory_path)

    with pytest.raises(OutboxError):
        outbox.append(make_open_transition())


@pytest.mark.parametrize(
    "raised",
    [
        OSError(28, "No space left on device"),  # ENOSPC — 디스크 용량 부족
        PermissionError(13, "Permission denied"),  # PermissionError는 OSError의 하위 클래스
    ],
)
def test_append_wraps_specific_os_errors_as_outbox_error(tmp_path, monkeypatch, raised):
    """디스크 용량 부족·권한 거부처럼 실제 배포 환경에서 나올 법한 구체적인
    OSError 종류로도 OutboxError 래핑이 성립하는지 확인한다. 원인 예외도
    체이닝돼야 호출부가 실제 원인을 로그로 남길 수 있다."""
    outbox = JsonlOutbox(tmp_path / "outbox.jsonl")

    def _raise(*args, **kwargs):
        raise raised

    monkeypatch.setattr("pathlib.Path.open", _raise)

    with pytest.raises(OutboxError) as excinfo:
        outbox.append(make_open_transition())
    assert excinfo.value.__cause__ is raised
